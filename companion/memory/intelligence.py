"""Real-time, exact-source GPT memory work, independent of the diary schedule."""

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from companion.hashing import content_hash
from companion.ids import uuid7
from companion.product.diary_intelligence import DiaryIntelligenceResult


class RealtimeMemoryService:
    version = "realtime-gpt-memory-v1"

    def __init__(self, *, understanding, timezone_name: str):
        self.understanding = understanding
        self.repository = understanding.repository
        self.owner_id = understanding.owner_id
        self.timezone_name = timezone_name

    async def run_once(self):
        token = uuid7()
        with self.repository.pool.connection() as c, c.transaction():
            jobs = c.execute("""SELECT * FROM havre.realtime_memory_jobs
                WHERE owner_id=%s AND ((status IN ('pending','retryable_failed') AND available_at<=clock_timestamp())
                 OR (status='leased' AND lease_expires_at<=clock_timestamp()))
                ORDER BY created_at,source_user_event_id FOR UPDATE SKIP LOCKED LIMIT 4""", (self.owner_id,)).fetchall()
            if not jobs:
                return None
            ids = [job['source_user_event_id'] for job in jobs]
            c.execute("""UPDATE havre.realtime_memory_jobs SET status='leased',lease_token=%s,
                lease_expires_at=clock_timestamp()+interval '10 minutes',attempt_count=attempt_count+1,
                error_code=NULL,updated_at=clock_timestamp() WHERE owner_id=%s AND source_user_event_id=ANY(%s::uuid[])""",
                (token,self.owner_id,ids))
        try:
            event_ids = [value for job in jobs for value in (job['source_user_event_id'],job['source_assistant_event_id'])]
            with self.repository.pool.connection() as c:
                rows=c.execute("""SELECT e.* FROM havre.events e JOIN havre.interaction_requests i
                    ON i.owner_id=e.owner_id AND i.request_id=e.request_id JOIN havre.route_decisions r
                    ON r.owner_id=e.owner_id AND r.request_id=e.request_id
                    WHERE e.owner_id=%s AND e.event_id=ANY(%s::uuid[])
                     AND e.privacy_class IN ('PUBLIC','NORMAL') AND e.cloud_eligible
                     AND (e.event_type='ASSISTANT_MESSAGE' OR e.memory_eligible)
                     AND i.status='completed' AND r.execution_environment='cloud'
                     AND r.selected_provider_id='openai-codex-chatgpt'
                     AND NOT EXISTS(SELECT 1 FROM havre.offline_source_revocations x WHERE x.owner_id=e.owner_id AND x.source_event_id=e.event_id)
                    ORDER BY e.recorded_at,e.event_id""",(self.owner_id,event_ids)).fetchall()
            if len(rows)!=len(set(event_ids)):
                raise ValueError('memory sources changed or are no longer eligible')
            events=[{**dict(row),'role':'user' if row['event_type']=='USER_MESSAGE' else 'assistant',
                'content':self.understanding._payload_text(row['payload']),'disposition':'cloud_summary'} for row in rows]
            zone=ZoneInfo(self.timezone_name)
            local_date=(events[-1]['recorded_at'].astimezone(zone)-timedelta(hours=5)).date()
            memories=self.understanding._review_memories(local_date=(datetime.now(zone)-timedelta(hours=5)).date(),timezone_name=self.timezone_name)
            source_hash=content_hash({'purpose':self.version,'source_set':self.understanding._source_set_hash(events,memories,memory_only=True)})
            request=self.understanding._request(local_date=local_date,timezone_name=self.timezone_name,
                source_set_hash=source_hash,cloud_events=events,private_count=0,
                review_memories=memories,memory_only=True)
            response=await self.understanding.provider.generate(request)
            parsed=DiaryIntelligenceResult.parse_provider_text(response.output_parts[0].text,strict_understanding=True)
            updates,beliefs=self.understanding._validated_updates(parsed,events,strict_sources=True)
            # Provider text cannot turn a memory job into a diary or contact job.
            result=DiaryIntelligenceResult(include_diary=False,memory_updates=updates,user_model_updates=beliefs)
            with self.repository.pool.connection() as c,c.transaction():
                current=c.execute("""SELECT source_user_event_id FROM havre.realtime_memory_jobs
                    WHERE owner_id=%s AND source_user_event_id=ANY(%s::uuid[]) AND status='leased'
                     AND lease_token=%s AND lease_expires_at>clock_timestamp() FOR UPDATE""",(self.owner_id,ids,token)).fetchall()
                if len(current)!=len(jobs):
                    return {'status':'lease_lost'}
                run_id=self.understanding._persist(local_date=local_date,timezone_name=self.timezone_name,
                    source_set_hash=source_hash,events=events,review_memories=memories,result=result,
                    request=request,response=response,status='completed',run_kind='realtime_memory',connection=c)
                c.execute("""UPDATE havre.realtime_memory_jobs SET status='completed',run_id=%s,
                    lease_token=NULL,lease_expires_at=NULL,updated_at=clock_timestamp()
                    WHERE owner_id=%s AND source_user_event_id=ANY(%s::uuid[]) AND lease_token=%s""",(run_id,self.owner_id,ids,token))
            return {'status':'completed','turns':len(jobs),'run_id':str(run_id)}
        except Exception as error:
            delay=self.understanding._retry_backoff(max(job['attempt_count'] for job in jobs)+1)
            with self.repository.pool.connection() as c,c.transaction():
                c.execute("""UPDATE havre.realtime_memory_jobs SET status='retryable_failed',error_code=%s,
                    available_at=%s,lease_token=NULL,lease_expires_at=NULL,updated_at=clock_timestamp()
                    WHERE owner_id=%s AND source_user_event_id=ANY(%s::uuid[]) AND status='leased' AND lease_token=%s""",
                    (type(error).__name__,datetime.now(UTC)+delay,self.owner_id,ids,token))
            raise
