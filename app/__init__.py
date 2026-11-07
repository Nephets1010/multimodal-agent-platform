"""多模态通用智能体开发平台。

本模块只暴露版本号，供 ``/health.version`` 与 FastAPI 应用元信息使用；
刻意不在此处导入任何业务模块，避免 ``import app`` 附带装配副作用。
"""

__version__ = "1.0.0"

__all__ = ["__version__"]
