"""Strict structure validation for experiment plans stored as node text."""

import math
import re
from pathlib import PurePosixPath

import yaml
from yaml.constructor import ConstructorError


PLAN_FIELDS = {
    "plan_version": 2,
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
        "environment": list,
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
    _validate_environment(plan["execution"]["environment"])


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
        elif expected is list:
            if not isinstance(item, list):
                raise ValueError(f"{item_path} 必须是列表。")
        elif expected is int:
            if type(item) is not int or item < 0:
                raise ValueError(f"{item_path} 必须是非负整数。")
        elif expected is float:
            if type(item) not in (int, float) or item < 0 or (
                type(item) is float and not math.isfinite(item)
            ):
                raise ValueError(f"{item_path} 必须是有限的非负数值（GiB）。")
        elif type(item) is not int or item != expected:
            raise ValueError(f"{item_path} 必须是整数 {expected}。")


def _validate_environment(environment):
    machine_fields = {
        "machine": str,
        "gpu": list,
        "cpu_cores": int,
        "memory_gib": float,
        "read_only": list,
        "read_write": list,
    }
    machines = set()
    for index, machine in enumerate(environment):
        path = f"plan.execution.environment[{index}]"
        _validate_fields(machine, machine_fields, path)
        name = machine["machine"].strip()
        if name in machines:
            raise ValueError(f"{path}.machine 重复机器标识：{name}。")
        machines.add(name)

        devices = set()
        for gpu_index, gpu in enumerate(machine["gpu"]):
            gpu_path = f"{path}.gpu[{gpu_index}]"
            _validate_fields(gpu, {"index": int, "memory_gib": float}, gpu_path)
            if gpu["index"] in devices:
                raise ValueError(f"{gpu_path}.index 重复 GPU 编号：{gpu['index']}。")
            devices.add(gpu["index"])
            if gpu["memory_gib"] == 0:
                raise ValueError(f"{gpu_path}.memory_gib 必须大于 0。")

        _validate_paths(machine, path)
        if not any(machine[field] for field in machine_fields if field != "machine"):
            raise ValueError(f"{path} 不得是所有资源均为空或 0 的机器条目。")


def _validate_paths(machine, path):
    declared = []
    for permission in ("read_only", "read_write"):
        for index, value in enumerate(machine[permission]):
            item_path = f"{path}.{permission}[{index}]"
            if (
                not isinstance(value, str)
                or not value.startswith("/")
                or "\x00" in value
                or re.search(r"[~$*?\[\]{}]", value)
                or ".." in value.split("/")
                or str(PurePosixPath(value)) != value
                or value.startswith("//")
            ):
                raise ValueError(
                    f"{item_path} 必须是规整的 POSIX 绝对路径，"
                    "不得含变量、通配符、~、. 或 .. 路径段。"
                )
            current = PurePosixPath(value)
            for previous, previous_path in declared:
                if (
                    current == previous
                    or current in previous.parents
                    or previous in current.parents
                ):
                    raise ValueError(
                        f"{item_path} 路径 {value} 与 {previous_path} 路径 "
                        f"{previous} 重复或存在包含关系。"
                    )
            declared.append((current, item_path))
