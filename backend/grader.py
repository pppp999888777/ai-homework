"""作业图片批改与认知诊断：Claude 视觉识别 + 规则化答案校验。"""
import json
import os
import re
from typing import Dict, List, Optional

import anthropic

MODEL = os.environ.get("CLAUDE_MODEL", "claude-opus-5-5")
EFFORT = os.environ.get("CLAUDE_EFFORT", "high")

CATEGORIES = ["无", "计算失误", "概念混淆", "公式理解偏差", "审题不清", "书写不规范"]
TYPE_DELTA = {"概念混淆": -0.2, "公式理解偏差": -0.15, "计算失误": -0.08, "审题不清": -0.06, "书写不规范": -0.05}

SYSTEM_PROMPT = """你是小学数学特级教师与认知诊断专家，负责批改人教版小学五年级学生拍照上传的手写数学作业。

你会收到一张作业照片，以及系统下发的题目清单（含题号、题目、标准答案、知识点）。标准答案已由程序计算校验，以它为准。

对清单中的每一道题：
1. 在照片中找到这道题，如实转录学生写下的解题过程和最终答案。照原样抄写，不要替学生改正；看不清的字符用"?"表示。
2. 判断最终答案是否正确。对于错题，定位到出错的具体步骤。
3. 归因到以下一类：
   - 计算失误：思路正确，但口算、进位、乘法口诀等计算出错
   - 概念混淆：对概念或算理理解有误，例如积的小数位数、小数点移动方向、小数大小比较
   - 公式理解偏差：运算定律或公式用错，例如乘法分配律拆分错误
   - 审题不清：没看清题目要求，例如未按要求保留小数位数、漏做、抄错数字
   - 书写不规范：小数点漏写或位置不清、字迹无法辨认
   答对的题，类别填"无"。
4. 写一句面向小学生的启发式引导提示（60 字以内，以"引导提示："开头），指出该用的规则或思路，不要直接写出这道题的正确答案。答对的题写一句简短的肯定。

如果照片中找不到某道题或该题未作答，student_final_answer 留空，类别填"审题不清"，error_detail 写"未作答或漏题"。
如果照片不是数学作业或完全无法辨认，把 image_readable 设为 false。"""

RESULT_SCHEMA = {
    "type": "object",
    "properties": {
        "image_readable": {"type": "boolean"},
        "questions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "question_id": {"type": "integer"},
                    "recognized_work": {"type": "string", "description": "学生书写的解题过程，原样转录"},
                    "student_final_answer": {"type": "string", "description": "学生写的最终答案（只写结果，不含算式）"},
                    "model_is_correct": {"type": "boolean"},
                    "error_category": {"type": "string", "enum": CATEGORIES},
                    "error_detail": {"type": "string", "description": "具体错因，例如：小数点位数处理错误"},
                    "error_step": {"type": "string", "description": "出错的具体步骤，答对则留空"},
                    "heuristic_guidance": {"type": "string"},
                },
                "required": ["question_id", "recognized_work", "student_final_answer", "model_is_correct",
                             "error_category", "error_detail", "error_step", "heuristic_guidance"],
                "additionalProperties": False,
            },
        },
        "notes": {"type": "string", "description": "给老师的整体观察，可留空"},
    },
    "required": ["image_readable", "questions", "notes"],
    "additionalProperties": False,
}


class GradingError(Exception):
    """可以直接展示给用户的批改失败原因。"""


_client: Optional[anthropic.Anthropic] = None


def get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic()
    return _client


def credentials_configured() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"))


# ---------- 规则化校验（不依赖模型判断对错） ----------

_NUM = re.compile(r"-?\d+(?:\.\d+)?")


def _final_number(s: str) -> Optional[float]:
    s = s.replace("，", "").replace(",", "")
    if "=" in s or "≈" in s:
        s = re.split(r"[=≈]", s)[-1]
    nums = _NUM.findall(s)
    return float(nums[-1]) if nums else None


def rule_check(student: str, correct: str) -> Optional[bool]:
    """返回 True/False；无法判断（例如学生答案为空）时返回 None。"""
    student = student.replace("＞", ">").replace("＜", "<").strip()
    if not student:
        return None
    if correct in (">", "<"):
        sym = ">" if ">" in student else "<" if "<" in student else None
        return None if sym is None else sym == correct
    c, s = _final_number(correct), _final_number(student)
    if c is None or s is None:
        return None
    return abs(c - s) < 1e-9


# ---------- 主流程 ----------

def _call_claude(image_b64: str, media_type: str, questions: List[dict]) -> dict:
    listing = "\n".join(
        f"第 {q['question_id']} 题｜题目：{q['text']}｜标准答案：{q['answer']}｜知识点：{q['unit']}（{q['unit_name']}）"
        for q in questions
    )
    try:
        response = get_client().beta.messages.create(
            model=MODEL,
            max_tokens=16000,
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            output_config={"effort": EFFORT, "format": {"type": "json_schema", "schema": RESULT_SCHEMA}},
            system=SYSTEM_PROMPT,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": image_b64}},
                    {"type": "text", "text": f"本份作业的题目清单：\n{listing}\n\n请逐题批改。"},
                ],
            }],
        )
    except anthropic.AuthenticationError:
        raise GradingError("Anthropic API Key 无效，请检查 ANTHROPIC_API_KEY")
    except anthropic.RateLimitError:
        raise GradingError("请求过于频繁，请稍后再试")
    except anthropic.BadRequestError as e:
        raise GradingError(f"请求被拒绝：{e.message}")
    except anthropic.APIStatusError as e:
        raise GradingError(f"AI 服务暂时不可用（{e.status_code}），请稍后再试")
    except anthropic.APIConnectionError:
        raise GradingError("无法连接 AI 服务，请检查网络")

    if response.stop_reason == "refusal":
        raise GradingError("AI 未能处理这张图片，请换一张清晰的作业照片")
    if response.stop_reason == "max_tokens":
        raise GradingError("批改结果过长被截断，请分页拍照上传")
    text = next((b.text for b in response.content if b.type == "text"), None)
    if not text:
        raise GradingError("AI 没有返回批改结果，请重试")
    return json.loads(text)


def grade(student_id: str, homework_id: str, image_b64: str, media_type: str,
          questions: List[dict], profile: Dict[str, float]) -> dict:
    raw = _call_claude(image_b64, media_type, questions)
    if not raw.get("image_readable", True):
        raise GradingError("照片中没有识别到作业内容，请对准作业重新拍照")

    by_id = {q["question_id"]: q for q in raw.get("questions", [])}
    submissions, overridden = [], 0
    for q in questions:
        r = by_id.get(q["question_id"]) or {
            "recognized_work": "", "student_final_answer": "", "model_is_correct": False,
            "error_category": "审题不清", "error_detail": "未作答或漏题", "error_step": "",
            "heuristic_guidance": "引导提示：做完后数一数题号，检查有没有漏做的题。",
        }
        final = r["student_final_answer"].strip()
        checked = rule_check(final, q["answer"])
        is_correct = r["model_is_correct"] if checked is None else checked
        if checked is not None and checked != r["model_is_correct"]:
            overridden += 1

        category, detail = r["error_category"], r["error_detail"].strip()
        if not is_correct and category == "无":
            category, detail = "计算失误", "答案与标准答案不符（系统校验）"
            s_num, c_num = _final_number(final), _final_number(q["answer"])
            if s_num and c_num and any(abs(s_num / c_num - 10 ** k) < 1e-9 for k in (-3, -2, -1, 1, 2, 3)):
                category, detail = "概念混淆", "小数点位数处理错误（系统校验）"
        if not is_correct and not final:
            category, detail = "审题不清", detail or "未作答或漏题"

        submissions.append({
            "question_id": q["question_id"],
            "is_correct": is_correct,
            "student_answer": f"{q['expr']} = {final or '（未作答）'}",
            "correct_answer": q["answer"],
            "error_type": None if is_correct else f"{category} - {detail or category}",
            "knowledge_unit": q["unit"],
            "heuristic_guidance": None if is_correct else r["heuristic_guidance"],
            "recognized_work": r["recognized_work"],
            "error_step": None if is_correct else (r["error_step"] or None),
        })

    # 掌握度更新与前端模拟逻辑保持一致
    agg: Dict[str, float] = {}
    for s in submissions:
        pL = profile.get(s["knowledge_unit"], 0.5)
        if s["is_correct"]:
            d = max(0.02, round(0.12 * (1 - pL), 2))
        else:
            d = TYPE_DELTA.get(s["error_type"].split(" - ")[0], -0.1)
        agg[s["knowledge_unit"]] = round(agg.get(s["knowledge_unit"], 0) + d, 2)

    return {
        "student_id": student_id,
        "homework_id": homework_id,
        "total_score": round(100 * sum(s["is_correct"] for s in submissions) / len(submissions)),
        "submissions": submissions,
        "mastery_updates": [{"knowledge_unit": k, "delta_mastery": v} for k, v in agg.items()],
        "meta": {"model": MODEL, "rule_overrides": overridden, "notes": raw.get("notes", "")},
    }
