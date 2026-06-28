import ast
import re
from typing import Any, Dict


def parse_strategy_parameters(source_code: str) -> Dict[str, Any]:
    """
    使用 AST 静态解析 Python 策略源码，提取 __init__ 参数用于生成前端动态表单
    """
    try:
        tree = ast.parse(source_code)
    except IndentationError as e:
        return {"status": "error", "message": f"代码缩进错误: {e.msg} (第 {e.lineno} 行)。请检查空格与 Tab。"}  # noqa: E501
    except SyntaxError as e:
        return {"status": "error", "message": f"代码语法错误: {e.msg} (第 {e.lineno} 行)"}  # noqa: E501

    strategies = []

    # 💡 优化 1: 仅遍历顶层节点 (tree.body)，直接屏蔽内部函数或嵌套类中的临时类
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            # 💡 优化 2: 启发式过滤辅助类，只提取像“策略”的类
            is_strategy = False
            # 规则 A: 类名包含 Strategy 或 Bot
            if "Strategy" in node.name or "Bot" in node.name:
                is_strategy = True
            # 规则 B: 继承了 BaseStrategy 等包含 Strategy 的基类
            for base in node.bases:
                if isinstance(base, ast.Name) and "Strategy" in base.id:
                    is_strategy = True

            if not is_strategy:
                continue

            # 遍历类内部的方法，寻找 __init__
            for class_body_item in node.body:
                if isinstance(class_body_item, ast.FunctionDef) and class_body_item.name == '__init__':  # noqa: E501
                    # 💡 提取 Docstring 并解析参数说明
                    docstring = ast.get_docstring(class_body_item) or ast.get_docstring(node) or ""  # noqa: E501
                    param_descs = {}
                    for line in docstring.split("\n"):
                        line = line.strip()
                        # 匹配 Sphinx 风格: `:param fast_ma: 快速均线周期`
                        m_sphinx = re.match(r':param\s+(\w+):\s*(.*)', line)
                        if m_sphinx:
                            param_descs[m_sphinx.group(1)] = m_sphinx.group(2).strip()
                            continue
                        # 匹配 Google 风格: `fast_ma (int): 快速均线周期` 或 `fast_ma: 快速均线周期`  # noqa: E501
                        m_google = re.match(r'^(\w+)\s*(?:\([^)]+\))?:\s*(.*)', line)
                        # 排除掉特殊的保留字
                        if m_google and m_google.group(1) not in ("param", "type", "return", "rtype"):  # noqa: E501
                            param_descs[m_google.group(1)] = m_google.group(2).strip()

                    params = []
                    args = class_body_item.args.args
                    defaults = class_body_item.args.defaults

                    # 默认值列表是右对齐的（从后往前匹配）
                    default_offset = len(args) - len(defaults)

                    for i, arg in enumerate(args):
                        # 排除框架自带的保留字
                        if arg.arg in ('self', 'args', 'kwargs', 'context'):
                            continue

                        param_info = {
                            "name": arg.arg,
                            "type": "string", # 兜底类型
                            "default": None,
                            "required": i < default_offset,
                            "description": param_descs.get(arg.arg, "")
                        }

                        # 1. 提取 Type Hints (如 pos_size: float)
                        if arg.annotation and isinstance(arg.annotation, ast.Name):
                            param_info["type"] = arg.annotation.id.lower()

                        # 2. 提取默认值 (如 fast_ma=10)
                        if i >= default_offset:
                            default_node = defaults[i - default_offset]
                            # 兼容 Python 3.8+ 的 ast.Constant
                            if isinstance(default_node, ast.Constant):
                                param_info["default"] = default_node.value
                                # 如果没有 Type Hint，通过默认值的类型智能推导
                                if type(default_node.value) is int:
                                    param_info["type"] = "int"
                                elif type(default_node.value) is float:
                                    param_info["type"] = "float"
                                elif type(default_node.value) is bool:
                                    param_info["type"] = "bool"

                        params.append(param_info)

                    if params:
                        strategies.append({
                            "class_name": node.name,
                            "parameters": params
                        })

    if not strategies:
        return {"status": "error", "message": "架构规范缺失: 未检测到继承自 BaseStrategy 的策略类，或缺失带有参数的 __init__ 方法。请将逻辑封装为标准策略 (第 1 行)"}  # noqa: E501

    return {"status": "success", "data": strategies}
