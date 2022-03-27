from transformers import AutoTokenizer, AutoModelForQuestionAnswering
from sklearn.feature_extraction.text import CountVectorizer
from flask import Blueprint, render_template
from flask_login import login_required
from module1.models import CoronaNet
from nltk.corpus import stopwords
from flask import request
from module1 import db

import numpy.linalg as LA
import numpy as np
import torch
import json

bp_annotation = Blueprint('annotation', __name__)

tokenizer = AutoTokenizer.from_pretrained("deepset/bert-base-cased-squad2")
model = AutoModelForQuestionAnswering.from_pretrained("deepset/bert-base-cased-squad2")


def setValue(policy, columnName, answer):
    if columnName == 'update_type':
        policy.update_type = answer

    if columnName == 'country':
        policy.country = answer

    return policy


@bp_annotation.route("/policies/save", methods=['POST'])
@login_required
def save():
    dataJson = request.data.decode("utf-8")
    data = json.loads(dataJson)

    policy = db.session.query(CoronaNet).filter_by(policy_id=data["pid"]).first()

    policy = setValue(policy, data['column'], data['answer'])
    # policy.update_type = data['answer']
    db.session.commit()

    return json.dumps({'success': True}), 200, {'ContentType': 'application/json'}


@bp_annotation.route("/policies/get_highlighting_text", methods=['GET', 'POST'])
@login_required
def get_highlighting_text():
    data = request.data.decode("utf-8").split("------")
    policy_id = data[0]
    summary = data[1]

    return summary

def signle_QA2(question, context):
    inputs = tokenizer.encode_plus(question, context, return_tensors="pt")
    answer_start_scores, answer_end_scores = model(**inputs)
    answer_start = torch.argmax(answer_start_scores)
    answer_end = torch.argmax(answer_end_scores) + 1
    answer = tokenizer.convert_tokens_to_string(tokenizer.convert_ids_to_tokens(inputs["input_ids"][0][answer_start:answer_end])).replace('[CLS]', '')

    if '[SEP]' in answer:
        answer = (answer.split('[SEP]')[1]).strip()

    if answer not in context:
        return ""
    return answer


def signle_QA(question, context, model_name):
    from transformers import pipeline

    nlp = pipeline('question-answering', model=model_name, tokenizer=model_name)
    QA_input = {
        'question': question,
        'context': context
    }
    res = nlp(QA_input)

    return res['answer']


def multi_QA(question, contexts, model_name):
    answers = ''
    for context in contexts:
        if context == '':
            continue

        answer = signle_QA(question, context, model_name)
        if answer != None and answer != "":
            if answers == '':
                answers = answer
            else:
                answers = answers + "|" + answer
    return answers


from sentence_transformers import SentenceTransformer
from sklearn.metrics.pairwise import cosine_similarity
model2 = SentenceTransformer('bert-base-nli-mean-tokens')

def multi_choice_QA(policy, options_list):
    options_list.insert(0, policy)
    # Encoding:
    sentence_embeddings = model2.encode(options_list)
    sentence_embeddings.shape

    # let's calculate cosine similarity for sentence 0:
    return cosine_similarity(
        [sentence_embeddings[0]],
        sentence_embeddings[1:]
    )


@bp_annotation.route("/policies/<int:policy_id>/annotation", methods=['GET', 'POST'])
@login_required
def get_annotation(policy_id):
    model_name = 'deepset/bert-base-cased-squad2'
    with open('./module1/static/questions.json', encoding="utf8") as f:
        q_objs = json.load(f)

        policy = CoronaNet.query.filter_by(policy_id=policy_id).first()
        context = policy.description.split('.')
        has_answer = False

        for q in q_objs:
            db_column_name = q["columnName"]
            obj_property = getattr(policy, db_column_name)

            # test
            # if answer == '':
            #     answer = 'A dimension other than the policy initiator'

            print(q["id"])
            if q["taskType"] == 1:
                options_list = []
                for option in q["options"]:
                    options_list.append(option["option"] if option["note"]=="" else option["note"])
                q["AI_QA_result"] = multi_choice_QA(policy, options_list)[0]
                m_cos = 0
                arr = q["AI_QA_result"].tolist()
                # max_cos = round(max(arr), 2)
                max_cos = max(arr)

                for i in range(0, len(q["AI_QA_result"])):
                    # q["options"][i]["cos"] = round(q["AI_QA_result"][i])
                    q["options"][i]["cos"] = q["AI_QA_result"][i]
                    if q["AI_QA_result"][i] == max_cos:
                        q["options"][i]["checked"] = "True"

                # for option in q["options"]:
                #     option_text = option["option"]
                #     cosine_similarity = max_cos(option_text, q["AI_QA_result"])
                #
                #     # cosine_similarity = 0.8
                #
                #     option["cos"] = cosine_similarity
                #
                #     if m_cos < cosine_similarity:
                #         m_cos = cosine_similarity

                if obj_property is None and obj_property == "":
                    for option in q["options"]:
                        if m_cos == option["cos"]:
                            q["answers"] = option["option"]
                else:
                    q["answers"] = obj_property
                    has_answer = True

                    # tmp = option["cosine_similarity"]
                    # print(cosine_similarity)
                    # print(tmp)

                if has_answer:
                    for option in q["options"]:
                        if option["option"] == q["answers"]:
                            option["checked"] = "True"
                            option["type"] = 1
                            break
                    for option in q["options"]:
                        if option["cos"] == max_cos:
                            option["type"] = 2
                            break
                else:
                    for option in q["options"]:
                        if option["cos"] == max_cos:
                            option["checked"] = "True"
                            option["type"] = 2
                            break
                q["has_answer"] = has_answer
            elif q["taskType"] == 2:
                if obj_property is None or obj_property == "":
                    q["answers"] = multi_QA(q["question"], context, model_name)
                else:
                    q["answers"] = obj_property
                    has_answer = True
                q["has_answer"] = has_answer

    summary_list = policy.description.split('\n')
    original_list = policy.original_text.split('\n')
    return render_template('annotation.html', policy=policy, questions=q_objs, summary_list=summary_list, original_list=original_list)


def max_cos(option, answers):
    max=0
    answers = answers.split('|')
    for answer in answers:
        c = cos(option, answer)
        if c > max:
            max = c

    return max


def cos(option, answer):
    cosine = 0

    options = []
    answers = []

    options.append(option)
    answers.append(answer)

    if len(options) > 0 and len(answers) > 0:
        stopWords = stopwords.words('english')
        vectorizer = CountVectorizer(stop_words=stopWords)

        option = vectorizer.fit_transform(options).toarray()[0]
        answer = vectorizer.transform(answers).toarray()[0]

        cosine = consine_cal(option, answer)

    return cosine


def consine_cal(v1, v2):
    a = np.inner(v1, v2)
    b = LA.norm(v1) * LA.norm(v2)
    if a == 0 or b == 0:
        return 0

    return round(a / b, 3)


@bp_annotation.route("/policies/<int:policy_id>/view", methods=['GET', 'POST'])
@login_required
def view(policy_id):
    policy = CoronaNet.query.filter_by(policy_id=policy_id).first().__dict__
    return render_template('view.html', policy=policy)

