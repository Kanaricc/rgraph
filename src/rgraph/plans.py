"""Strict structure validation for experiment plans stored as node text."""

import yaml
from yaml.constructor import ConstructorError


PLAN_FIELDS = {
    "plan_version": 1,
    "title": str,
    "question": str,
    "hypothesis": str,
    "design": str,
    "evaluation": str,
    "decision": {
        "supported": str,
        "not_supported": str,
        "inconclusive": str,
    },
    "execution": {
        "environment": str,
        "steps": str,
        "prohibited_actions": str,
        "artifacts": str,
        "stop_condition": str,
    },
}


class PlanLoader(yaml.SafeLoader):
    def construct_mapping(self, node, deep=False):
        mapping = {}
        for key_node, value_node in node.value:
            key = self.construct_object(key_node, deep=deep)
            if not isinstance(key, str):
                raise ConstructorError(None, None, "字段名必须是字符串", key_node.start_mark)
            if key in mapping:
                raise ConstructorError(None, None, f"重复字段：{key}", key_node.start_mark)
            mapping[key] = self.construct_object(value_node, deep=deep)
        return mapping


def validate_plan(text):
    """Validate one YAML document without altering its original formatting."""
    try:
        plan = yaml.load(text, Loader=PlanLoader)
    except yaml.YAMLError as exc:
        raise ValueError(f"实验计划必须是有效的单个 YAML 文档：{exc}") from exc
    _validate_fields(plan, PLAN_FIELDS, "plan")


def _validate_fields(value, fields, path):
    if not isinstance(value, dict):
        raise ValueError(f"{path} 必须是对象。")
    missing = fields.keys() - value.keys()
    unknown = value.keys() - fields.keys()
    if missing:
        raise ValueError(f"{path} 缺少字段：{', '.join(sorted(missing))}。")
    if unknown:
        raise ValueError(f"{path} 包含未知字段：{', '.join(sorted(unknown))}。")
    for name, expected in fields.items():
        item = value[name]
        item_path = f"{path}.{name}"
        if isinstance(expected, dict):
            _validate_fields(item, expected, item_path)
        elif expected is str:
            if not isinstance(item, str) or not item.strip():
                raise ValueError(f"{item_path} 必须是非空白字符串。")
        elif type(item) is not int or item != expected:
            raise ValueError(f"{item_path} 必须是整数 {expected}。")
