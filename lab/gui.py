"""Mobile Kivy interface. Demo, Bybit public candles, CoinGlass snapshots (optional)."""
import threading
from kivy.app import App
from kivy.clock import Clock
from kivy.graphics import Color,Line,Rectangle
from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.spinner import Spinner
from kivy.uix.textinput import TextInput
from kivy.uix.widget import Widget

from .sources import synthetic_scenario,fetch_bybit_candles,fetch_coinglass_snapshot
from .detection import describe
from .backtest import simulate

BG=(.052,.075,.12,1);TEXT=(.91,.96,1,1);MUTED=(.57,.67,.78,1)
CYAN=(.22,.84,.91,1);HEAT=(1,.46,.26,1)

class Graph(Widget):
    def __init__(self,**kw):
        super().__init__(**kw)
        self.candles=[];self.clusters=[]
        self.bind(pos=self.draw,size=self.draw)
    def set_data(self,candles,clusters):
        self.candles=list(candles);self.clusters=list(clusters);self.draw()
    def draw(self,*args):
        self.canvas.clear()
        with self.canvas:
            Color(.085,.12,.19,1);Rectangle(pos=self.pos,size=self.size)
            if not self.candles:return
            x0,y0=self.x+dp(12),self.y+dp(16)
            width,height=max(dp(1),self.width-dp(24)),max(dp(1),self.height-dp(32))
            values=[c.close for c in self.candles]
            lowest=min([c.low for c in self.candles]+[p.price for p in self.clusters] or values)
            highest=max([c.high for c in self.candles]+[p.price for p in self.clusters] or values)
            span=max(1e-6,highest-lowest);n=len(values)
            def ypos(v):return y0+(v-lowest)/span*height
            # Background horizontal map: strength is schematic, not market execution.
            max_i=max([p.intensity for p in self.clusters] or [1])
            for p in self.clusters:
                Color(1,.38,.1,min(.8,.15+.6*p.intensity/max_i))
                Line(points=[x0,ypos(p.price),x0+width,ypos(p.price)],width=1+2*p.intensity/max_i)
            Color(.14,.68,.86,1)
            pts=[]
            for i,p in enumerate(values):
                pts.extend((x0+width*i/max(1,n-1),ypos(p)))
            if len(pts)>=4:Line(points=pts,width=dp(1.5))
            Color(.28,.35,.44,1)
            for j in (0,1,2,3,4):
                yy=y0+j*height/4
                Line(points=[x0,yy,x0+width,yy],width=.5)
            Color(1,.78,.34,1)
            y=ypos(values[-1]);Line(points=[x0,y,x0+width,y],width=1,dash_length=5,dash_offset=3)

def btn(label,action):
    b=Button(text=label,size_hint_y=None,height=dp(46),font_size="14sp",bold=True,
             background_normal="",background_color=(.11,.29,.43,1),color=TEXT)
    b.bind(on_release=action);return b

class MainView(BoxLayout):
    def __init__(self,**kw):
        super().__init__(orientation="vertical",padding=dp(12),spacing=dp(9),**kw)
        head=Label(text="LIQUIDATION LAB 0.2",color=CYAN,size_hint_y=None,height=dp(40),bold=True,font_size="19sp")
        self.add_widget(head)
        self.mode=Spinner(text="Учебный рост",values=("Учебный рост","Учебное снижение","Учебный боковик"),
                          size_hint_y=None,height=dp(44),background_normal="",background_color=(.12,.2,.3,1),color=TEXT)
        self.mode.bind(text=lambda *_:self.demo())
        self.add_widget(self.mode)
        self.graph=Graph(size_hint_y=.54)
        self.add_widget(self.graph)
        options=BoxLayout(spacing=dp(7),size_hint_y=None,height=dp(46))
        options.add_widget(btn("DEMO",lambda *_:self.demo()))
        options.add_widget(btn("BYBIT BTC",lambda *_:self.from_bybit()))
        options.add_widget(btn("BACKTEST",lambda *_:self.backtest()))
        self.add_widget(options)
        self.info=Label(text="",color=TEXT,halign="left",valign="top",size_hint_y=.31,font_size="13sp")
        self.info.bind(size=lambda w,v:setattr(w,"text_size",(max(0,v[0]-dp(10)),v[1])))
        self.add_widget(self.info)
        row=BoxLayout(spacing=dp(6),size_hint_y=None,height=dp(42))
        self.key=TextInput(hint_text="CoinGlass API key (optional)",password=True,multiline=False,font_size="12sp")
        row.add_widget(self.key)
        b=btn("MAP",lambda *_:self.from_coinglass());b.size_hint_x=.28
        row.add_widget(b)
        self.add_widget(row)
        self.candles=[];self.clusters=[]
        Clock.schedule_once(lambda *_:self.demo(),0)

    def demo(self):
        name={"Учебный рост":"up","Учебное снижение":"down","Учебный боковик":"sideways"}.get(self.mode.text,"up")
        self.candles,self.clusters=synthetic_scenario(name)
        self.show("ИСКУССТВЕННЫЕ ДАННЫЕ")

    def show(self,origin):
        self.graph.set_data(self.candles,self.clusters)
        d=describe(self.candles)
        f=lambda x:"—" if x is None else f"{x:.2f}"
        setup=d["setup"]
        band=f"{setup.bottom:.2f}–{setup.top:.2f}" if setup else "не обнаружен"
        self.info.text=(f"Источник: {origin}\nЦена: {f(d['price'])} | RSI(14): {f(d['rsi'])}\n"
                       f"EMA20: {f(d['ema_fast'])} | EMA50: {f(d['ema_slow'])}\n"
                       f"ATR14: {f(d['atr'])}\nИмпульс → боковик: {band}\n"
                       f"Кластеры: {len(self.clusters)} (отдельный слой)\n"
                       "Исследовательский режим, без реальных сделок.")

    def async_call(self,operation,callback):
        self.info.text="Загрузка данных…"
        def work():
            try:result=operation()
            except Exception as ex:
                Clock.schedule_once(lambda dt:self.set_error(str(ex)),0);return
            Clock.schedule_once(lambda dt:callback(result),0)
        threading.Thread(target=work,daemon=True).start()

    def set_error(self,message):
        self.info.text="Ошибка источника: "+message

    def from_bybit(self):
        def received(candles):
            self.candles=candles;self.clusters=[]
            self.show("BYBIT OHLC (без карты ликвидаций)")
        self.async_call(lambda:fetch_bybit_candles(limit=500),received)

    def from_coinglass(self):
        key=self.key.text.strip()
        if not key:
            self.set_error("Нужен ключ API CoinGlass с доступом к liquidation map.");return
        def received(clusters):
            self.clusters=clusters
            self.key.text=""
            self.show("CoinGlass: ТЕКУЩИЙ СНИМОК карты")
        self.async_call(lambda:fetch_coinglass_snapshot(key),received)

    def backtest(self):
        if len(self.candles)<100:
            self.info.text="Для бэктеста недостаточно свечей.";return
        result=simulate(self.candles)
        self.info.text=(f"ВИРТУАЛЬНЫЙ БЭКТЕСТ ({len(self.candles)} свечей)\n"
                        f"Сделок: {result['trade_count']} | Доходность: {result['return_pct']:.2f}%\n"
                        f"Доля прибыльных: {result['win_rate_pct']:.1f}%\n"
                        f"Max Drawdown: {result['max_drawdown_pct']:.2f}%\n"
                        "Учтены комиссии и проскальзывание.\n"
                        "Карта CoinGlass НЕ используется в историческом бэктесте.")

class LiquidationLabApp(App):
    def build(self):
        self.title="Liquidation Lab"
        return MainView()
