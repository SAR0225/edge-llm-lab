import json

with open("eval_questions.json", encoding="utf-8") as file:
    questions = json.load(file)

for item in questions:
    print(f"题目 {item['id']}：{item['question']}")
    print(f"参考答案：{item['expected_answer']}")
    print()