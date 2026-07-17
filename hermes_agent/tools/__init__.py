import importlib
import os
import pkgutil

"""
Agent Tools 自动扫描挂载中心
利用 pkgutil 自动发现当前包目录下的所有 .py 模块，并动态导入。
配合 @register_tool 装饰器，实现新增 Tool 文件的“零配置、热插拔”。
"""

package_dir = os.path.dirname(__file__)

for _, module_name, _ in pkgutil.iter_modules([package_dir]):
    # 动态导入当前包下的所有模块
    importlib.import_module(f"{__name__}.{module_name}")
