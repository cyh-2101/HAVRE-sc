from __future__ import annotations

import unittest
from companion.commitments.recognition import completion_intent, match_task, task_tokens


class CompletionRecognitionTests(unittest.TestCase):
    def test_owner_reports_in_natural_order(self):
        for message in (
            "ece385lab2.1demo+quiz搞完了", "我的 CS 101 作业做完了",
            "我已经提交了报告", "I completed ECE 210 Lab Alpha", "done",
        ):
            with self.subTest(message=message):
                self.assertTrue(completion_intent(message))

    def test_report_with_deadline_and_compact_spelling(self):
        message="昨天我把ece385 lab1report写完了"
        self.assertTrue(completion_intent(message))
        self.assertTrue(match_task(message,course_name="ECE 385",task_name="ECE 385 Lab 1 Report（9/8 11:59 PM）")[1])
        self.assertEqual(match_task("ece385 lab2report写完了",course_name="ECE 385",task_name="ECE 385 Lab 1 Report（9/8 11:59 PM）"),(0,False))
        for text in ("她把ece385 lab1report写完了","我还没写完lab1","lab1快写完了","我说明天写完lab1","我说过‘写完了’吗"):
            self.assertFalse(completion_intent(text),text)

    def test_not_owner_completion(self):
        for message in (
            "I haven't completed Lab 1", "Lab 1 is not done",
            "我还没做完lab1", "我明天完成lab1", "如果我完成了lab1",
            "室友的lab1搞完了", "She completed Lab 1", "我只完成了一半",
            "Lab 1 almost done", "我说过‘完成了’吗", "我完成了么？",
            "室友已经弄完了lab1", "同学终于把上周一直在赶的那个很难很难的lab1提交了",
            "lab1搞完了吗", "我lab1完成了吧",
        ):
            with self.subTest(message=message):
                self.assertFalse(completion_intent(message))

    def test_numbers_and_composite_tasks_are_not_interchangeable(self):
        self.assertIn("1", task_tokens("quiz1"))
        self.assertFalse(match_task("2做完了", course_name="CS 100", task_name="Lab 2")[1])
        args = dict(course_name="ECE 385", task_name="Lab 2.1 Demo + Quiz 1")
        self.assertEqual(match_task("ece385 lab2.2 demo+quiz1做完了", **args), (0, False))
        self.assertFalse(match_task("ece385lab2.1demo搞完了", **args)[1])
        self.assertTrue(match_task("ece385lab2.1demo+quiz搞完了", **args)[1])
        self.assertTrue(match_task("385lab2.1和quiz弄完了",
            course_name="ECE 385", task_name="ECE 385 Lab 2.1 Demo + Quiz 1（9/4）")[1])
        self.assertFalse(match_task("385lab2.1弄完了",
            course_name="ECE 385", task_name="ECE 385 Lab 2.1 Demo + Quiz 1（9/4）")[1])


if __name__ == "__main__":
    unittest.main()
