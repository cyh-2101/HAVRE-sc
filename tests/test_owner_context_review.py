"""Owner preference artifacts retain exact evidence and never become training rows."""
import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from html.parser import HTMLParser
from evals.context_ab_blind import canonical_hash,write,digest,read
from scripts.prepare_owner_context_review import prepare,record_choices,QUESTIONS,POLICY,render


class OwnerReviewPacketTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.run=self.root/'run';self.run.mkdir()
        (self.run/'blind').mkdir();(self.run/'keys').mkdir()
        source={'current_message':'Synthetic question <script>alert(1)</script>',
            'shared_authoritative_clock':{'target_received_at':'2026-09-06T12:00:00-05:00'},
            'pre_target_evidence':[{'role':'user','at':'earlier','text':'Synthetic prior fact.'}],
            'outputs':[{'label':'opaque-first','text':'Synthetic short answer.'},{'label':'opaque-second','text':'Synthetic longer answer with a follow-up.'}]}
        write(self.run/'blind/pair-001.NORMAL.json',source)
        write(self.run/'keys/pair-001.LOCAL_ONLY.json',{'packet_hash':canonical_hash(source),'key':{'opaque-first':'full','opaque-second':'simple'}})
        write(self.run/'run-spec.NORMAL.json',{'schedule':[{'case_id':'synthetic','replicate':1}]})
        write(self.run/'review-lock.LOCAL_ONLY.json',{'blind/pair-001.NORMAL.json':digest(self.run/'blind/pair-001.NORMAL.json')})
        self.output=self.root/'owner'

    def packet(self):return prepare(self.run,[1],self.output)

    def choices(self,packet):
        return {'schema_version':1,'packet_hash':packet['packet_hash'],'choices':[
            {'case_id':'choice-01','like_havre':'A','continue_chat':'tie'}]}

    def test_blind_page_escapes_content_and_has_no_architecture_mapping(self):
        packet=self.packet();html=render(packet)
        self.assertIn('&lt;script&gt;alert(1)&lt;/script&gt;',html)
        self.assertNotIn('"full"',html);self.assertNotIn('"simple"',html)
        self.assertNotIn('opaque-first',html);self.assertNotIn('source-key',html)
        self.assertEqual(packet['questions'],QUESTIONS);self.assertEqual(packet['policy'],POLICY)
        self.assertFalse(list(self.output.glob('*choices*')))
        class Links(HTMLParser):
            def handle_starttag(self,tag,attrs):
                for key,value in attrs:
                    if key in ('src','href','action'):raise AssertionError('external resource')
        Links().feed(html)

    def test_explicit_choices_create_local_immutable_regression_receipt(self):
        packet=self.packet();submitted=self.root/'submitted.json';write(submitted,self.choices(packet))
        target=self.root/'receipt.json';receipt=record_choices(self.output,submitted,target)
        self.assertFalse(receipt['policy']['training_eligible']);self.assertFalse(receipt['policy']['cloud_eligible'])
        self.assertEqual(receipt['evidence'][0]['answers'],packet['cases'][0]['answers'])
        with self.assertRaisesRegex(ValueError,'immutable'):record_choices(self.output,submitted,target)

    def test_changed_packet_or_choice_target_fails_closed(self):
        packet=self.packet();choices=self.choices(packet);choices['packet_hash']='changed'
        submitted=self.root/'submitted.json';write(submitted,choices)
        with self.assertRaisesRegex(ValueError,'another packet'):record_choices(self.output,submitted,self.root/'receipt.json')
        path=self.output/'owner-packet.LOCAL_ONLY.json';path.write_text('{}',encoding='utf-8')
        with self.assertRaisesRegex(ValueError,'sealed owner'):record_choices(self.output,submitted,self.root/'receipt.json')

    def test_duplicate_missing_or_architecture_choice_is_rejected(self):
        packet=self.packet()
        for index,rows in enumerate(([],self.choices(packet)['choices']*2,[{'case_id':'choice-01','like_havre':'full','continue_chat':'B'}])):
            submitted=self.root/f'submitted-{index}.json';data=self.choices(packet);data['choices']=rows;write(submitted,data)
            with self.assertRaises(ValueError):record_choices(self.output,submitted,self.root/'receipt.json')

    def test_modified_locked_source_and_repeated_generation_are_rejected(self):
        path=self.run/'blind/pair-001.NORMAL.json';original=path.read_bytes();path.write_text('{}','utf-8')
        with self.assertRaisesRegex(ValueError,'changed after review lock'):self.packet()
        path.write_bytes(original)
        spec=self.run/'run-spec.NORMAL.json';spec.write_text('{"schedule":[{"replicate":2}]}','utf-8')
        with self.assertRaisesRegex(ValueError,'repeats'):self.packet()

    def test_recreating_packet_cannot_rerandomize_existing_owner_choices(self):
        self.packet()
        with self.assertRaisesRegex(ValueError,'preserve existing'):self.packet()


if __name__=='__main__':unittest.main()
