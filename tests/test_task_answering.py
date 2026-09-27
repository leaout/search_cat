import unittest

from plugin_platform.task_answering import (
    anti_fraud_answer,
    match_question,
    parse_feedback_answer,
    parse_options,
)


class TaskAnsweringTests(unittest.TestCase):
    def test_parse_options_and_feedback(self):
        options = parse_options(['A 直接告诉他', 'Ｂ：拒绝并通过官方渠道确认'])
        self.assertEqual([item['letter'] for item in options], ['A', 'B'])
        self.assertEqual(parse_feedback_answer('回答错误，正确答案：Ｂ'), 'B')

    def test_match_question(self):
        result = match_question('仙术士装备什么类型的武器？', [
            {'q': '仙术士装备什么类型的武器', 'ans': 'D'},
        ])
        self.assertEqual(result['ans'], 'D')

    def test_anti_fraud_rule(self):
        answer, confidence = anti_fraud_answer('遇到骗子索要验证码怎么办？', [
            {'letter': 'A', 'text': '把验证码告诉他'},
            {'letter': 'B', 'text': '拒绝并通过官方渠道核实'},
        ])
        self.assertEqual(answer, 'B')
        self.assertGreater(confidence, 0.7)


if __name__ == '__main__':
    unittest.main()
