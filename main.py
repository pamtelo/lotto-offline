"""로또 6/45 오프라인 번호 추천 + 온디바이스 재학습 (Kivy)."""

import os

from kivy.config import Config
from kivy.utils import platform

if platform not in ("android", "ios"):
    # PC 에서는 휴대폰 비율 창으로 띄운다 (Window import 전에 설정해야 적용됨)
    Config.set("graphics", "width", "400")
    Config.set("graphics", "height", "820")

from kivy.app import App
from kivy.clock import mainthread
from kivy.core.text import DEFAULT_FONT, LabelBase
from kivy.core.window import Window
from kivy.factory import Factory
from kivy.lang import Builder
from kivy.metrics import dp
from kivy.properties import (
    BooleanProperty,
    ListProperty,
    NumericProperty,
    StringProperty,
)
from kivy.uix.behaviors import ButtonBehavior
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.label import Label
from kivy.uix.textinput import TextInput
from kivy.uix.widget import Widget

import evaluation as ev_mod
from ml_engine import PICK, LottoEngine
from storage import LottoStorage, ValidationError

APP_DIR = os.path.dirname(os.path.abspath(__file__))
ASSET_DIR = os.path.join(APP_DIR, "assets")
FONT_DIR = os.path.join(APP_DIR, "fonts")
GAME_LABELS = "ABCDE"
HISTORY_LIMIT = 30
EVAL_HISTORY_LIMIT = 30

C_BG = (0.949, 0.957, 0.965, 1)       # #F2F4F6
C_ERROR = (0.941, 0.267, 0.322, 1)    # #F04452
C_SUCCESS = (0.012, 0.698, 0.424, 1)  # #03B26C
C_DIM_BALL = [0.929, 0.937, 0.945, 1]  # 맞히지 못한 번호
C_DIM_TEXT = (0.690, 0.722, 0.757, 1)

SYSTEM_FONTS = [
    "/system/fonts/NotoSansCJK-Regular.ttc",           # Android
    "/system/fonts/NotoSansKR-Regular.otf",
    "C:/Windows/Fonts/malgun.ttf",                     # Windows
    "/System/Library/Fonts/AppleSDGothicNeo.ttc",      # macOS
    "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",  # Linux
]


def register_fonts():
    """
    기본 폰트(Roboto)에는 한글이 없으므로 기본 폰트 자체를 교체한다.
    번들된 Pretendard 가 있으면 사용하고, 없으면 시스템 한글 폰트로 대체.
    강조(SemiBold)용 폰트 이름을 반환한다.
    """
    regular, semibold, bold = (
        os.path.join(FONT_DIR, f"Pretendard-{w}.otf") for w in ("Regular", "SemiBold", "Bold")
    )
    if os.path.exists(regular):
        bold = bold if os.path.exists(bold) else None
        LabelBase.register(DEFAULT_FONT, regular, fn_bold=bold)
        if os.path.exists(semibold):
            LabelBase.register("Emphasis", semibold, fn_bold=bold)
            return "Emphasis"
        return DEFAULT_FONT
    for path in SYSTEM_FONTS:
        if os.path.exists(path):
            LabelBase.register(DEFAULT_FONT, path)
            break
    return DEFAULT_FONT


EMPHASIS_FONT = register_fonts()
Window.clearcolor = C_BG
Window.softinput_mode = "below_target"  # 키보드가 입력창을 가리지 않도록


def ball_color_for(n):
    # 동행복권 공 색상 구간
    if n <= 10:
        return [0.984, 0.769, 0.0, 1]   # #FBC400
    if n <= 20:
        return [0.412, 0.784, 0.949, 1]  # #69C8F2
    if n <= 30:
        return [1.0, 0.447, 0.447, 1]   # #FF7272
    if n <= 40:
        return [0.667, 0.667, 0.667, 1]  # #AAAAAA
    return [0.690, 0.847, 0.251, 1]     # #B0D840


KV = """
#:import dp kivy.metrics.dp
#:import sp kivy.metrics.sp
#:import FadeTransition kivy.uix.screenmanager.FadeTransition
#:set C_BG (0.949, 0.957, 0.965, 1)
#:set C_CARD (1, 1, 1, 1)
#:set C_PRIMARY (0.192, 0.510, 0.965, 1)
#:set C_PRIMARY_DARK (0.106, 0.392, 0.855, 1)
#:set C_PRIMARY_SOFT (0.910, 0.953, 1, 1)
#:set C_TEXT (0.098, 0.122, 0.157, 1)
#:set C_SUB (0.420, 0.463, 0.518, 1)
#:set C_HINT (0.690, 0.722, 0.757, 1)
#:set C_LINE (0.898, 0.910, 0.922, 1)
#:set C_FIELD (0.976, 0.980, 0.984, 1)
#:set C_WARN (0.961, 0.471, 0.0, 1)
#:set C_WARN_SOFT (1, 0.957, 0.902, 1)

<Label>:
    color: C_TEXT

<Caption@Label>:
    font_size: '13sp'
    color: C_SUB
    size_hint_y: None
    height: self.texture_size[1]
    text_size: self.width, None
    halign: 'left'

<CardCanvas>:
    canvas.before:
        Color:
            rgba: 0, 0, 0, 0.05
        BoxShadow:
            pos: self.pos
            size: self.size
            offset: 0, -dp(2)
            blur_radius: dp(14)
            border_radius: dp(18), dp(18), dp(18), dp(18)
        Color:
            rgba: C_CARD
        RoundedRectangle:
            pos: self.pos
            size: self.size
            radius: [dp(18)]

<Card@BoxLayout+CardCanvas>:
    orientation: 'vertical'
    padding: dp(18)
    spacing: dp(10)

<Ball>:
    size_hint: None, None
    size: dp(40), dp(40)
    pos_hint: {'center_y': 0.5}
    bold: True
    font_size: self.height * 0.4
    color: 1, 1, 1, 1
    canvas.before:
        Color:
            rgba: 0, 0, 0, 0.08
        Ellipse:
            pos: self.x, self.y - dp(1.5)
            size: self.size
        Color:
            rgba: self.ball_color
        Ellipse:
            pos: self.pos
            size: self.size

<GameRow>:
    size_hint_y: None
    height: dp(72)
    padding: dp(16), dp(12)
    spacing: dp(12)
    Label:
        text: root.label
        size_hint: None, None
        size: sp(30), sp(30)
        pos_hint: {'center_y': 0.5}
        font_name: app.font_emphasis
        font_size: '15sp'
        color: C_PRIMARY
        canvas.before:
            Color:
                rgba: C_PRIMARY_SOFT
            RoundedRectangle:
                pos: self.pos
                size: self.size
                radius: [dp(9)]
    BoxLayout:
        id: balls
        spacing: dp(6)

<HistoryRow>:
    size_hint_y: None
    height: sp(44)
    padding: 0, dp(6)
    spacing: dp(4)
    canvas.after:
        Color:
            rgba: C_LINE
        Line:
            points: self.x, self.y, self.right, self.y
    Label:
        id: draw_label
        size_hint_x: None
        width: sp(58)
        font_name: app.font_emphasis
        font_size: '14sp'
        text_size: self.size
        halign: 'left'
        valign: 'middle'
    BoxLayout:
        id: balls
        spacing: dp(4)

<NumInput>:
    input_filter: 'int'
    input_type: 'number'
    multiline: False
    write_tab: False
    halign: 'center'
    font_size: '18sp'
    font_name: app.font_emphasis
    background_normal: ''
    background_active: ''
    background_color: 0, 0, 0, 0
    foreground_color: C_TEXT
    hint_text_color: C_HINT
    cursor_color: C_PRIMARY
    cursor_width: dp(2)
    padding: [dp(6), (self.height - self.line_height) / 2]
    # TextInput 자체 canvas 에 그리면 내부 글자색 지정 순서와 충돌하므로 테두리는 감싸는 NumBox 가 그린다
    on_focus: if self.parent: self.parent.focused = args[1]

<NumBox@BoxLayout>:
    focused: False
    canvas.before:
        Color:
            rgba: C_FIELD
        RoundedRectangle:
            pos: self.pos
            size: self.size
            radius: [dp(12)]
        Color:
            rgba: C_PRIMARY if self.focused else C_LINE
        Line:
            rounded_rectangle: (self.x, self.y, self.width, self.height, dp(12))
            width: dp(1.3) if self.focused else dp(1)

<PrimaryButton@Button>:
    size_hint_y: None
    height: max(dp(56), self.texture_size[1] + dp(24))
    font_size: '16sp'
    bold: True
    color: 1, 1, 1, 1
    background_normal: ''
    background_down: ''
    background_color: 0, 0, 0, 0
    canvas.before:
        Color:
            rgba: C_PRIMARY_DARK if self.state == 'down' else C_PRIMARY
        RoundedRectangle:
            pos: self.pos
            size: self.size
            radius: [dp(14)]

<StatusChip@Label>:
    busy: False
    size_hint: None, None
    size: self.texture_size[0] + dp(24), max(dp(30), self.texture_size[1] + dp(12))
    pos_hint: {'center_y': 0.5}
    font_size: '12sp'
    font_name: app.font_emphasis
    color: C_WARN if self.busy else C_PRIMARY
    canvas.before:
        Color:
            rgba: C_WARN_SOFT if self.busy else C_PRIMARY_SOFT
        RoundedRectangle:
            pos: self.pos
            size: self.size
            radius: [self.height / 2]

<ChipButton>:
    size_hint: None, None
    size: self.texture_size[0] + dp(26), max(dp(34), self.texture_size[1] + dp(14))
    pos_hint: {'center_y': 0.5}
    font_size: '13sp'
    font_name: app.font_emphasis
    color: (1, 1, 1, 1) if self.active else C_PRIMARY
    canvas.before:
        Color:
            rgba: (C_PRIMARY_DARK if self.state == 'down' else C_PRIMARY) if self.active else (C_LINE if self.state == 'down' else C_PRIMARY_SOFT)
        RoundedRectangle:
            pos: self.pos
            size: self.size
            radius: [self.height / 2]

<SectionTitle@Label>:
    font_size: '17sp'
    bold: True
    size_hint_y: None
    height: max(sp(24), self.texture_size[1])
    text_size: self.width, None
    halign: 'left'
    valign: 'middle'

<NoteBox@Label>:
    font_size: '13sp'
    color: C_SUB
    size_hint_y: None
    text_size: self.width - dp(28), None
    height: self.texture_size[1] + dp(22) if self.text else 0
    halign: 'left'
    canvas.before:
        Color:
            rgba: C_BG
        RoundedRectangle:
            pos: self.pos
            size: self.size
            radius: [dp(12)]

<MetricRow>:
    size_hint_y: None
    height: max(sp(30) if root.header else sp(44), title_label.texture_size[1] + dp(14))
    spacing: dp(8)
    canvas.after:
        Color:
            rgba: C_LINE
        Line:
            points: self.x, self.y, self.right, self.y
    Label:
        id: title_label
        text: root.title
        font_size: '12sp' if root.header else '14sp'
        color: C_SUB if root.header else C_TEXT
        text_size: self.width, None
        halign: 'left'
        valign: 'middle'
    Label:
        text: root.value
        size_hint_x: None
        width: sp(72)
        font_size: '12sp' if root.header else '16sp'
        font_name: app.font_emphasis
        color: C_SUB if root.header else C_PRIMARY
        text_size: self.size
        halign: 'right'
        valign: 'middle'
    Label:
        text: root.baseline
        size_hint_x: None
        width: sp(64)
        font_size: '12sp' if root.header else '14sp'
        color: C_SUB
        text_size: self.size
        halign: 'right'
        valign: 'middle'

<EvalGameRow>:
    size_hint_y: None
    height: dp(40)
    spacing: dp(10)
    Label:
        text: root.label
        size_hint: None, None
        size: sp(26), sp(26)
        pos_hint: {'center_y': 0.5}
        font_name: app.font_emphasis
        font_size: '13sp'
        color: C_PRIMARY
        canvas.before:
            Color:
                rgba: C_PRIMARY_SOFT
            RoundedRectangle:
                pos: self.pos
                size: self.size
                radius: [dp(8)]
    BoxLayout:
        id: balls
        spacing: dp(4)
    Label:
        text: root.result
        size_hint_x: None
        width: sp(70)
        font_size: '13sp'
        font_name: app.font_emphasis
        color: C_PRIMARY if root.won else C_SUB
        text_size: self.size
        halign: 'right'
        valign: 'middle'

<EvalHistoryRow>:
    size_hint_y: None
    height: max(sp(44), detail_label.texture_size[1] + dp(14))
    spacing: dp(8)
    canvas.after:
        Color:
            rgba: C_LINE
        Line:
            points: self.x, self.y, self.right, self.y
    Label:
        text: root.draw_text
        size_hint_x: None
        width: sp(58)
        font_name: app.font_emphasis
        font_size: '14sp'
        text_size: self.size
        halign: 'left'
        valign: 'middle'
    Label:
        text: root.result
        font_size: '14sp'
        color: C_PRIMARY if root.won else C_TEXT
        text_size: self.size
        halign: 'left'
        valign: 'middle'
    Label:
        id: detail_label
        text: root.detail
        size_hint_x: None
        width: sp(118)
        font_size: '12sp'
        color: C_SUB
        text_size: self.width, None
        halign: 'right'
        valign: 'middle'

<TabItem>:
    orientation: 'vertical'
    padding: 0, dp(9), 0, dp(7)
    spacing: dp(3)
    Image:
        source: root.icon
        size_hint: None, None
        size: dp(24), dp(24)
        pos_hint: {'center_x': 0.5}
        color: C_TEXT if root.active else C_HINT
    Label:
        text: root.text
        font_size: '12sp'
        font_name: app.font_emphasis
        color: C_TEXT if root.active else C_HINT

<RootView>:
    orientation: 'vertical'
    # 폴드 펼침 화면처럼 넓으면 콘텐츠를 app.max_content_width 폭으로 가운데 정렬
    gutter: max(0, (self.width - dp(app.max_content_width)) / 2)

    BoxLayout:
        size_hint_y: None
        height: dp(28) + sp(32)
        padding: dp(20) + root.gutter, 0
        Label:
            text: '로또 6/45'
            font_size: '22sp'
            bold: True
            text_size: self.size
            halign: 'left'
            valign: 'middle'
        StatusChip:
            id: status_chip
            text: app.status_text
            busy: app.is_training

    ScreenManager:
        id: sm
        transition: FadeTransition(duration=0.12)

        Screen:
            name: 'recommend'
            BoxLayout:
                orientation: 'vertical'
                BoxLayout:
                    orientation: 'vertical'
                    size_hint_y: None
                    height: self.minimum_height
                    padding: dp(20) + root.gutter, dp(4), dp(20) + root.gutter, dp(8)
                    spacing: dp(2)
                    Label:
                        id: rec_title
                        text: app.target_label
                        font_size: '14sp'
                        font_name: app.font_emphasis
                        color: C_PRIMARY
                        size_hint_y: None
                        height: sp(22)
                        text_size: self.size
                        halign: 'left'
                        valign: 'middle'
                    BoxLayout:
                        size_hint_y: None
                        height: max(sp(36), confirm_chip.height)
                        spacing: dp(8)
                        Label:
                            text: '이번 주 추천 번호'
                            font_size: '24sp'
                            bold: True
                            text_size: self.size
                            halign: 'left'
                            valign: 'middle'
                        ChipButton:
                            id: confirm_chip
                            text: '확정 완료' if app.rec_confirmed else '이 번호로 확정'
                            active: app.rec_confirmed
                            on_release: app.on_confirm()
                    Label:
                        id: rec_status
                        text: app.rec_caption
                        font_size: '13sp'
                        color: C_SUB
                        size_hint_y: None
                        height: self.texture_size[1] + dp(4)
                        text_size: self.width, None
                        halign: 'left'
                    Label:
                        text: app.confirm_caption
                        font_size: '12sp'
                        color: C_PRIMARY if app.rec_confirmed else C_SUB
                        size_hint_y: None
                        height: self.texture_size[1] + dp(4)
                        text_size: self.width, None
                        halign: 'left'
                ScrollView:
                    do_scroll_x: False
                    bar_width: dp(3)
                    GridLayout:
                        id: games_box
                        cols: 1
                        spacing: dp(12)
                        padding: dp(20) + root.gutter, dp(8)
                        size_hint_y: None
                        height: self.minimum_height
                BoxLayout:
                    size_hint_y: None
                    height: self.minimum_height
                    padding: dp(20) + root.gutter, dp(12)
                    PrimaryButton:
                        text: '새로운 5게임 추천받기'
                        on_release: app.on_new_recommendation()

        Screen:
            name: 'manage'
            ScrollView:
                do_scroll_x: False
                bar_width: dp(3)
                BoxLayout:
                    orientation: 'vertical'
                    size_hint_y: None
                    height: self.minimum_height
                    padding: dp(16) + root.gutter, dp(4), dp(16) + root.gutter, dp(16)
                    spacing: dp(14)
                    Card:
                        size_hint_y: None
                        height: self.minimum_height
                        Label:
                            text: '당첨 번호 등록'
                            font_size: '17sp'
                            bold: True
                            size_hint_y: None
                            height: sp(24)
                            text_size: self.size
                            halign: 'left'
                            valign: 'middle'
                        Caption:
                            text: '추첨 결과를 저장하면 모델이 바로 다시 학습해요'
                        BoxLayout:
                            size_hint_y: None
                            height: sp(78)
                            spacing: dp(10)
                            BoxLayout:
                                orientation: 'vertical'
                                spacing: dp(4)
                                Caption:
                                    text: '회차'
                                NumBox:
                                    NumInput:
                                        id: draw_no_input
                                        max_chars: 5
                                        hint_text: '회차'
                            BoxLayout:
                                orientation: 'vertical'
                                spacing: dp(4)
                                size_hint_x: None
                                width: dp(110)
                                Caption:
                                    text: '보너스 (선택)'
                                NumBox:
                                    NumInput:
                                        id: bonus_input
                        Caption:
                            text: '당첨 번호 6개 (1~45)'
                        GridLayout:
                            cols: 6
                            size_hint_y: None
                            height: sp(52)
                            spacing: dp(6)
                            NumBox:
                                NumInput:
                                    id: n1
                            NumBox:
                                NumInput:
                                    id: n2
                            NumBox:
                                NumInput:
                                    id: n3
                            NumBox:
                                NumInput:
                                    id: n4
                            NumBox:
                                NumInput:
                                    id: n5
                            NumBox:
                                NumInput:
                                    id: n6
                        Widget:
                            size_hint_y: None
                            height: dp(2)
                        PrimaryButton:
                            id: save_button
                            text: '당첨 번호 저장 및 모델 재학습'
                            on_release: app.on_save_draw()
                        Label:
                            id: manage_status
                            font_size: '13sp'
                            size_hint_y: None
                            height: self.texture_size[1] if self.text else 0
                            text_size: self.width, None
                            halign: 'center'
                    Card:
                        spacing: dp(4)
                        size_hint_y: None
                        height: self.minimum_height
                        BoxLayout:
                            size_hint_y: None
                            height: sp(26)
                            Label:
                                text: '등록된 회차'
                                font_size: '16sp'
                                bold: True
                                text_size: self.size
                                halign: 'left'
                                valign: 'middle'
                            Label:
                                text: app.history_caption
                                font_size: '13sp'
                                color: C_SUB
                                text_size: self.size
                                halign: 'right'
                                valign: 'middle'
                        GridLayout:
                            id: history_box
                            cols: 1
                            size_hint_y: None
                            height: self.minimum_height

        Screen:
            name: 'report'
            ScrollView:
                do_scroll_x: False
                bar_width: dp(3)
                BoxLayout:
                    id: report_box
                    orientation: 'vertical'
                    size_hint_y: None
                    height: self.minimum_height
                    padding: dp(16) + root.gutter, dp(4), dp(16) + root.gutter, dp(16)
                    spacing: dp(14)
                    Card:
                        size_hint_y: None
                        height: self.minimum_height
                        SectionTitle:
                            text: '누적 성적'
                        Caption:
                            text: app.report_caption
                        GridLayout:
                            id: metrics_box
                            cols: 1
                            size_hint_y: None
                            height: self.minimum_height
                        NoteBox:
                            text: app.report_note
                    Card:
                        id: latest_card
                        size_hint_y: None
                        height: self.minimum_height
                        SectionTitle:
                            text: app.latest_title
                        Caption:
                            text: app.latest_caption
                        GridLayout:
                            id: latest_box
                            cols: 1
                            spacing: dp(2)
                            size_hint_y: None
                            height: self.minimum_height
                    Card:
                        id: eval_history_card
                        spacing: dp(4)
                        size_hint_y: None
                        height: self.minimum_height
                        SectionTitle:
                            text: '회차별 기록'
                        GridLayout:
                            id: eval_history_box
                            cols: 1
                            size_hint_y: None
                            height: self.minimum_height

    BoxLayout:
        size_hint_y: None
        height: dp(46) + sp(18)
        padding: root.gutter, 0
        canvas.before:
            Color:
                rgba: C_CARD
            Rectangle:
                pos: self.pos
                size: self.size
            Color:
                rgba: C_LINE
            Line:
                points: self.x, self.top, self.right, self.top
        TabItem:
            icon: app.asset('tab_recommend.png')
            text: '번호 추천'
            active: sm.current == 'recommend'
            on_release: sm.current = 'recommend'
        TabItem:
            icon: app.asset('tab_manage.png')
            text: '당첨 번호 관리'
            active: sm.current == 'manage'
            on_release: sm.current = 'manage'
        TabItem:
            icon: app.asset('tab_report.png')
            text: '성적표'
            active: sm.current == 'report'
            on_release: sm.current = 'report'
"""


class Ball(Label):
    number = NumericProperty(0)
    ball_color = ListProperty([0.7, 0.7, 0.7, 1])

    def on_number(self, *_):
        n = int(self.number)
        self.text = str(n)
        self.ball_color = ball_color_for(n)


class CardCanvas(Widget):
    """KV 의 <CardCanvas> 규칙으로 흰 둥근 카드 + 그림자를 그리는 믹스인."""


class GameRow(BoxLayout, CardCanvas):
    label = StringProperty("")
    numbers = ListProperty([])

    def on_kv_post(self, base_widget):
        self.ids.balls.bind(width=self._resize_balls)

    def on_numbers(self, *_):
        box = self.ids.balls
        box.clear_widgets()
        for n in self.numbers:
            box.add_widget(Ball(number=n))
        self._resize_balls()

    def _resize_balls(self, *_):
        # 좁은 화면에서도 6개가 한 줄에 들어가도록 카드 폭에 맞춰 공 크기 조절
        box = self.ids.balls
        size = max(dp(22), min(dp(42), (box.width - box.spacing * (PICK - 1)) / PICK))
        for ball in box.children:
            ball.size = (size, size)


class HistoryRow(BoxLayout):
    def __init__(self, draw, **kwargs):
        super().__init__(**kwargs)
        self.ids.draw_label.text = f"{draw['draw_no']}회"
        box = self.ids.balls
        for n in draw["numbers"]:
            box.add_widget(self._small_ball(n))
        if draw.get("bonus"):
            box.add_widget(Label(text="+", size_hint_x=None, width=dp(10),
                                 color=(0.69, 0.72, 0.76, 1)))
            box.add_widget(self._small_ball(draw["bonus"]))

    @staticmethod
    def _small_ball(n):
        return small_ball(n, dp(26))


def small_ball(n, size, dim=False):
    # 생성자 kwargs 는 KV 규칙의 dp() 표현식에 덮어써지므로 생성 후 지정
    ball = Ball(number=n)
    ball.size = (size, size)
    if dim:
        ball.ball_color = C_DIM_BALL
        ball.color = C_DIM_TEXT
    return ball


class ChipButton(ButtonBehavior, Label):
    active = BooleanProperty(False)


class MetricRow(BoxLayout):
    title = StringProperty("")
    value = StringProperty("")
    baseline = StringProperty("")
    header = BooleanProperty(False)


class EvalGameRow(BoxLayout):
    label = StringProperty("")
    result = StringProperty("")
    won = BooleanProperty(False)

    def __init__(self, game, winning, **kwargs):
        super().__init__(**kwargs)
        for n in game:
            self.ids.balls.add_widget(small_ball(n, dp(28), dim=n not in winning))


class EvalHistoryRow(BoxLayout):
    draw_text = StringProperty("")
    result = StringProperty("")
    detail = StringProperty("")
    won = BooleanProperty(False)


class TabItem(ButtonBehavior, BoxLayout):
    icon = StringProperty("")
    text = StringProperty("")
    active = BooleanProperty(False)


class NumInput(TextInput):
    max_chars = NumericProperty(2)

    def insert_text(self, substring, from_undo=False):
        room = self.max_chars - len(self.text) + len(self.selection_text)
        if room <= 0:
            return
        return super().insert_text(substring[:room], from_undo=from_undo)


class RootView(BoxLayout):
    gutter = NumericProperty(0)


Builder.load_string(KV)


class LottoApp(App):
    title = "로또 6/45"
    icon = os.path.join(ASSET_DIR, "icon.png")

    status_text = StringProperty("준비 중")
    is_training = BooleanProperty(False)
    target_label = StringProperty("")
    rec_caption = StringProperty("")
    history_caption = StringProperty("")
    rec_confirmed = BooleanProperty(False)
    confirm_caption = StringProperty("")
    report_caption = StringProperty("")
    report_note = StringProperty("")
    latest_title = StringProperty("")
    latest_caption = StringProperty("")
    font_emphasis = StringProperty(EMPHASIS_FONT)
    max_content_width = NumericProperty(560)  # dp

    def asset(self, name):
        return os.path.join(ASSET_DIR, name)

    def build(self):
        self.storage = LottoStorage(
            os.path.join(self.user_data_dir, "lotto.db"), seed_dir=APP_DIR
        )
        self.engine = LottoEngine(self.storage, self.user_data_dir)
        self._regen_after_train = False
        self._save_summary = ""
        self.current_rec_id = None
        self.current_target = None
        self.root_view = RootView()
        # ids 는 약한 참조라, 빈 성적표일 때 트리에서 떼어 두는 카드는 강한 참조로 붙잡아 둔다
        ids = self.root_view.ids
        self._report_cards = (ids.latest_card.__self__, ids.eval_history_card.__self__)
        return self.root_view

    def on_start(self):
        model_loaded = self.engine.load_model()
        self.refresh_history()
        self.refresh_report()
        self.reset_draw_input()

        target = self.storage.latest_draw_no() + 1
        saved = self.storage.latest_recommendation(target)
        if saved and model_loaded:
            self.show_recommendations(target, saved["games"], saved["id"])
        else:
            self.on_new_recommendation()

        if self.engine.needs_retrain():
            # 모델이 없던 상태의 추천은 휴리스틱 결과이므로 학습 후 다시 뽑는다
            self.start_retrain(regenerate=not model_loaded)
        self.update_status()

    # ------------------------------------------------------------ recommend
    def on_new_recommendation(self):
        target, games, _, rec_id = self.engine.generate_recommendations(n_games=5)
        self.show_recommendations(target, games, rec_id)

    def show_recommendations(self, target, games, rec_id):
        self.current_target, self.current_rec_id = target, rec_id
        self.target_label = f"다음 회차 · {target}회"
        box = self.root_view.ids.games_box
        box.clear_widgets()
        for label, game in zip(GAME_LABELS, games):
            row = GameRow(label=label)
            row.numbers = game
            box.add_widget(row)
        self.update_confirm_state()

    def on_confirm(self):
        if self.current_rec_id is None or self.rec_confirmed:
            return
        self.storage.confirm_recommendation(self.current_rec_id)
        self.update_confirm_state()

    def update_confirm_state(self):
        official = self.storage.official_recommendation(self.current_target)
        other_confirmed = bool(official and official["is_confirmed"])
        self.rec_confirmed = other_confirmed and official["id"] == self.current_rec_id
        if self.rec_confirmed:
            self.confirm_caption = f"{self.current_target}회 성적은 이 5게임으로 매겨요"
        elif other_confirmed:
            self.confirm_caption = "앞서 확정한 다른 세트로 채점해요. 이 세트로 바꾸려면 확정을 누르세요"
        else:
            self.confirm_caption = "확정하지 않으면 이 회차에 처음 받은 추천으로 채점해요"

    def update_status(self):
        self.is_training = self.engine.is_training
        meta = self.engine.meta
        if self.is_training:
            self.status_text = "● 학습 중"
        elif meta:
            self.status_text = f"{meta['backend']} · 학습 완료"
        else:
            self.status_text = "준비 중"

        if meta:
            self.rec_caption = (
                f"{meta['trained_draws']:,}회차 당첨 이력을 학습한 모델이 고른 5게임이에요"
            )
        else:
            self.rec_caption = "모델 학습 전이라 출현 빈도 통계로 임시 추천했어요"

    # -------------------------------------------------------------- retrain
    def start_retrain(self, regenerate=True):
        self._regen_after_train = self._regen_after_train or regenerate
        self.engine.retrain_async(on_done=self._on_train_done, on_error=self._on_train_error)
        self.update_status()

    @mainthread
    def _on_train_done(self, meta):
        if not self.engine.is_training:
            if self._regen_after_train:
                self._regen_after_train = False
                self.on_new_recommendation()
            self.set_manage_status(
                f"{self._save_summary}재학습 완료 · {meta['backend']} · "
                f"샘플 {meta['samples']:,}개 · {meta['train_seconds']}초"
            )
            self._save_summary = ""
        self.update_status()

    @mainthread
    def _on_train_error(self, exc):
        self.set_manage_status(f"재학습 실패: {exc}", error=True)
        self.update_status()

    # ---------------------------------------------------------------- manage
    def _number_inputs(self):
        ids = self.root_view.ids
        return [ids[f"n{i}"] for i in range(1, 7)]

    def on_save_draw(self):
        ids = self.root_view.ids
        try:
            draw_no, nums, bonus = self.storage.add_draw(
                ids.draw_no_input.text.strip(),
                [w.text.strip() for w in self._number_inputs()],
                ids.bonus_input.text.strip(),
            )
        except ValidationError as exc:
            self.set_manage_status(str(exc), error=True)
            return

        for w in self._number_inputs() + [ids.bonus_input]:
            w.text = ""
        self.refresh_history()
        self.reset_draw_input()

        # 재학습이 모델을 바꾸기 전에, 추천 시점에 저장해 둔 결과로 채점한다
        self._save_summary = f"{draw_no}회차 저장 완료. {self._score_draw(draw_no, nums, bonus)}"
        self.set_manage_status(f"{self._save_summary}학습 진행 중...")
        self.start_retrain(regenerate=True)

    def _score_draw(self, draw_no, nums, bonus):
        rec = self.storage.official_recommendation(draw_no)
        if not rec:
            return "이 회차는 미리 받은 추천이 없어 채점하지 않았어요. "
        ev = ev_mod.evaluate_draw(draw_no, nums, bonus, rec)
        self.storage.save_evaluation(ev)
        self.refresh_report()
        return f"추천 채점: {ev_mod.best_result_text(ev)} (성적표 탭 참고). "

    def set_manage_status(self, text, error=False):
        label = self.root_view.ids.manage_status
        label.text = text
        label.color = C_ERROR if error else C_SUCCESS

    def reset_draw_input(self):
        self.root_view.ids.draw_no_input.text = str(self.storage.latest_draw_no() + 1)

    def refresh_history(self):
        self.history_caption = f"총 {self.storage.count_draws():,}회"
        box = self.root_view.ids.history_box
        box.clear_widgets()
        for draw in self.storage.list_draws(limit=HISTORY_LIMIT):
            box.add_widget(HistoryRow(draw))

    # ---------------------------------------------------------------- report
    def refresh_report(self):
        ids = self.root_view.ids
        evals = self.storage.list_evaluations()
        summary = ev_mod.summarize(evals)

        metrics = ids.metrics_box
        metrics.clear_widgets()
        for card in self._report_cards:
            if card.parent:
                card.parent.remove_widget(card)

        if not summary:
            self.report_caption = "추천을 받은 회차의 당첨 번호를 입력하면 자동으로 채점돼요"
            self.report_note = (
                "추천 화면의 5게임을 그 회차가 끝난 뒤 당첨 번호와 비교합니다. "
                "확정한 세트가 있으면 그것으로, 없으면 그 회차에 처음 받은 추천으로 채점해 "
                "여러 번 다시 뽑아 성적을 부풀릴 수 없어요."
            )
            return

        self.report_caption = (
            f"{summary['draws']}회차 · {summary['games']}게임 채점 "
            f"(확정 {summary['confirmed_draws']}회) · 같은 조건의 무작위 추천과 비교"
        )
        rows = [
            ("", "이 앱", "무작위", True),
            ("게임당 평균 적중", f"{summary['hits_per_game']:.2f}개",
             f"{ev_mod.RANDOM_HITS_PER_GAME:.2f}개", False),
            ("5등 이상 비율", f"{summary['prize_rate']:.1%}",
             f"{ev_mod.RANDOM_PRIZE_RATE:.1%}", False),
        ]
        if summary["auc"] is not None:
            rows += [
                ("당첨 번호 점수 순위 AUC", f"{summary['auc']:.3f}",
                 f"{ev_mod.RANDOM_AUC:.3f}", False),
                (f"상위 {ev_mod.TOP_K}위 안 당첨 번호", f"{summary['top_k']:.2f}개",
                 f"{ev_mod.RANDOM_TOP_K:.2f}개", False),
            ]
        for title, value, baseline, header in rows:
            metrics.add_widget(MetricRow(title=title, value=value, baseline=baseline, header=header))
        self.report_note = self._report_note(summary)

        latest = evals[0]
        self.latest_title = f"{latest['draw_no']}회 채점 결과"
        basis = "확정한 세트" if latest["confirmed"] else "확정 없음 · 처음 받은 추천"
        self.latest_caption = f"{basis} 기준 · {ev_mod.best_result_text(latest)}"
        box = ids.latest_box
        box.clear_widgets()
        box.add_widget(HistoryRow({"draw_no": latest["draw_no"], "numbers": latest["numbers"],
                                   "bonus": latest["bonus"]}))
        winning = set(latest["numbers"])
        for label, game, hits, rank in zip(GAME_LABELS, latest["games"],
                                           latest["hits"], latest["ranks"]):
            result = f"{hits}개 · {ev_mod.PRIZE_NAMES[rank]}" if rank else f"{hits}개"
            box.add_widget(EvalGameRow(game, winning, label=label, result=result, won=bool(rank)))
        if latest["winner_positions"]:
            positions = " · ".join(str(p) for p in sorted(latest["winner_positions"]))
            box.add_widget(Factory.Caption(
                text=f"당첨 번호의 모델 점수 순위: {positions}위 "
                     f"(무작위라면 평균 {ev_mod.RANDOM_MEAN_POSITION:.0f}위)",
                padding=(0, dp(8), 0, 0),
            ))

        history = ids.eval_history_box
        history.clear_widgets()
        for ev in evals[:EVAL_HISTORY_LIMIT]:
            avg = sum(ev["hits"]) / len(ev["hits"])
            detail = f"평균 {avg:.1f}개"
            if ev["auc"] is not None:
                detail += f" · AUC {ev['auc']:.2f}"
            history.add_widget(EvalHistoryRow(
                draw_text=f"{ev['draw_no']}회",
                result=("확정 · " if ev["confirmed"] else "")
                + ev_mod.best_result_text(ev).replace(" 적중", ""),
                detail=detail,
                won=any(ev["ranks"]),
            ))

        for card in self._report_cards:
            ids.report_box.add_widget(card)

    @staticmethod
    def _report_note(summary):
        diff = summary["hits_per_game"] - ev_mod.RANDOM_HITS_PER_GAME
        band = ev_mod.hits_noise_band(summary["games"])
        if not summary["reliable"]:
            return (
                f"아직 {summary['draws']}회차뿐이라 판단하기 일러요. "
                f"{ev_mod.MIN_RELIABLE_DRAWS}회차 이상 쌓였을 때 무작위 열과 비교해 보세요. "
                "매 회차는 독립적인 추첨이라 무작위와 비슷하게 나오는 것이 정상이에요."
            )
        if abs(diff) <= band:
            return (
                f"게임당 적중 차이 {diff:+.2f}개는 무작위로 골라도 생기는 범위(±{band:.2f}) 안이에요. "
                "모델이 무작위보다 낫다고 볼 근거는 아직 없어요."
            )
        direction = "높아요" if diff > 0 else "낮아요"
        return (
            f"게임당 적중이 무작위보다 {abs(diff):.2f}개 {direction}(우연 범위 ±{band:.2f} 밖). "
            "다만 추첨은 독립 시행이라 다음 회차까지 이어진다는 보장은 없어요."
        )


if __name__ == "__main__":
    LottoApp().run()
