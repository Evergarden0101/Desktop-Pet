"""User-facing text, in Chinese and English."""

from __future__ import annotations

import random

ZH = {
    "call_husband": "喊老公",
    "headpat": "摸摸头",
    "come_here": "到我这儿来",
    "pause": "暂停",
    "resume": "继续",
    "reset": "送回桌面",
    "add_pet": "再来一只",
    "remove_pet": "让她休息",
    "quit": "退出",
    "tray": "桌面宠物",
    "about": "关于",
    "manager": "角色管理",
    "import_image": "从图片导入…",
    "rebuild": "重新生成",
    "rename": "重命名",
    "delete": "删除",
    "on_desktop": "桌面上的数量",
    "size": "大小",
    "speed": "速度",
    "settings": "设置",
    "about_text": ("桌面宠物\n\n右键点我可以喊老公。\n"
                   "拖动可以把我拿起来，松手我会掉下去。\n"
                   "我会沿着窗口边缘爬来爬去。\n\n"
                   "在「角色管理」里可以从图片导入新角色。"),
}

EN = {
    "call_husband": "Call Husband",
    "headpat": "Head Pat",
    "come_here": "Come Here",
    "pause": "Pause",
    "resume": "Resume",
    "reset": "Send To Desktop",
    "add_pet": "One More",
    "remove_pet": "Let Her Rest",
    "quit": "Quit",
    "tray": "Desktop Pet",
    "about": "About",
    "manager": "Character Manager",
    "import_image": "Import image...",
    "rebuild": "Rebuild",
    "rename": "Rename",
    "delete": "Delete",
    "on_desktop": "On desktop",
    "size": "Size",
    "speed": "Speed",
    "settings": "Settings",
    "about_text": ("Desktop Pet\n\nRight-click me to call your husband.\n"
                   "Drag to pick me up, let go and I fall.\n"
                   "I crawl along the edges of your windows.\n\n"
                   "Import new characters from an image in the Character Manager."),
}

HUSBAND_ZH = ["老公~", "老公抱抱！", "老公你看我！", "老公，陪我玩嘛~",
              "老公老公老公！", "老公我饿了…", "老公亲亲！", "老公不许走~"]

HUSBAND_EN = ["Honey~", "Hubby, hug me!", "Look at me, dear!", "Come play with me~",
              "Husband! Husband!", "I'm hungry, honey...", "Kiss me!", "Don't go~"]

HEADPAT_ZH = ["嘿嘿~", "好舒服…", "再摸摸嘛", "喵~"]
HEADPAT_EN = ["Hehe~", "That's nice...", "More please", "Nya~"]


class Strings:
    def __init__(self, language: str = "auto"):
        self.lang = self._resolve(language)
        self._table = ZH if self.lang == "zh" else EN

    @staticmethod
    def _resolve(language: str) -> str:
        if language in ("zh", "en"):
            return language
        try:
            from PySide6.QtCore import QLocale

            name = QLocale.system().name()
        except Exception:
            name = ""
        return "zh" if name.startswith("zh") else "en"

    def __getitem__(self, key: str) -> str:
        return self._table.get(key, key)

    def husband(self) -> str:
        return random.choice(HUSBAND_ZH if self.lang == "zh" else HUSBAND_EN)

    def headpat(self) -> str:
        return random.choice(HEADPAT_ZH if self.lang == "zh" else HEADPAT_EN)
