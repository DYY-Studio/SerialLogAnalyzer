"""凭据管理对话框：输入 / 更新 / 删除某 Profile 的 API Key。

行为约定（见 ``DESIGN.md`` §13）：
- 输入内容默认仅用于本次会话，不自动写入系统钥匙串；
- 用户勾选“保存到系统钥匙串”时才调用 :meth:`KeyringStore.save`；
- 钥匙串不可用时置灰保存选项并提示回退来源。
"""

from __future__ import annotations

from PySide6.QtWidgets import QDialog

__all__ = ["CredentialDialog"]


class CredentialDialog(QDialog):
    """API Key 输入与保存对话框。

    参数:
        keyring: 钥匙串适配器（用于探测可用性与保存）。
        profile_id: 目标 Profile 标识，同时作为钥匙串账号名。
        parent: 可选父窗口。
    """

    def __init__(
        self,
        keyring: object,
        profile_id: str,
        parent: QDialog | None = None,
    ) -> None:
        raise NotImplementedError

    def secret(self) -> str:
        """返回用户输入的密钥（未输入时为空串）。"""

        raise NotImplementedError

    def save_to_keyring(self) -> bool:
        """返回用户是否勾选了“保存到系统钥匙串”。"""

        raise NotImplementedError
