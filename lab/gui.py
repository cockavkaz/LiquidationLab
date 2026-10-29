"""Kivy Windows-first research UI: causal candle replay, OHLC and explanations."""
import threading
from datetime import datetime, timezone

from kivy.app import App
from kivy.clock import Clock
from kivy.core.window import Window
from kivy.graphics import Color, Line, Rectangle
from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.slider import Slider
from kivy.uix.spinner import Spinner
from kivy.uix.textinput import TextInput
from kivy.uix.popup import Popup
from kivy.uix.scrollview import ScrollView
from kivy.uix.widget import Widget

from .backtest import simulate
from .history import fetch_bybit_history
from .indicators import ema
from .replay import ReplaySession
from .validation import validate_history, export_validation, short_summary
from .sources import (synthetic_scenario, fetch_coinglass_snapshot,
                      load_candles_csv, save_candles_csv)

TEXT = (.90, .94, .99, 1)
MUTED = (.58, .70, .80, 1)
TEAL = (.28, .85, .88, 1)
GREEN = (.20, .79, .58, 1)
RED = (.94, .33, .39, 1)
GOLD = (1, .74, .27, 1)


def button(title, fn, width=None):
    b = Button(text=title, font_size='13sp', bold=True, color=TEXT,
               background_normal='', background_color=(.12, .30, .44, 1))
    if width:
        b.size_hint_x = None
        b.width = dp(width)
    b.bind(on_release=fn)
    return b


def label(text='', size='13sp', height=None, color=TEXT, bold=False):
    l = Label(text=text, color=color, font_size=size, bold=bold,
              halign='left', valign='middle')
    if height:
        l.size_hint_y = None
        l.height = dp(height)
    l.bind(size=lambda w, _: setattr(w, 'text_size', (max(1, w.width-dp(10)), w.height)))
    return l


def spinner(text, values, width):
    return Spinner(text=text, values=values, size_hint_x=None, width=dp(width),
                   font_size='12sp', color=TEXT, background_normal='',
                   background_color=(.13, .24, .36, 1))


class CandleGraph(Widget):
    """Draws only historical candles through a user-visible cursor."""
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.candles = ()
        self.end_index = -1
        self.frame = None
        self.clusters = ()
        self.window_bars = 95
        self.bind(pos=self.redraw, size=self.redraw)

    def show(self, candles, end_index, frame, clusters=()):
        self.candles = candles
        self.end_index = end_index
        self.frame = frame
        self.clusters = clusters
        self.redraw()

    def redraw(self, *_):
        self.canvas.clear()
        with self.canvas:
            Color(.075, .105, .17, 1)
            Rectangle(pos=self.pos, size=self.size)
            if not self.candles or self.end_index < 0:
                return
            right = min(self.end_index, len(self.candles)-1)
            left = max(0, right-self.window_bars+1)
            visible = self.candles[left:right+1]
            if not visible:
                return
            x0, y0 = self.x+dp(12), self.y+dp(16)
            w = max(dp(1), self.width-dp(24))
            h = max(dp(1), self.height-dp(32))
            low = min(c.low for c in visible)
            high = max(c.high for c in visible)
            setup = self.frame.setup if self.frame else None
            if setup:
                low = min(low, setup.bottom)
                high = max(high, setup.top)
            if self.frame and self.frame.position:
                p = self.frame.position
                low = min(low, p['stop'], p['entry'], p['target'])
                high = max(high, p['stop'], p['entry'], p['target'])
            if self.clusters:
                # Cluster snapshot is NEVER shown on historical replay frames.
                low = min(low, *(v.price for v in self.clusters))
                high = max(high, *(v.price for v in self.clusters))
            margin = max((high-low)*.06, .0001)
            low -= margin
            high += margin
            span = max(high-low, 1e-8)
            y = lambda p: y0+(p-low)/span*h
            width_candle = w/max(1, len(visible))
            cx = lambda i: x0 + (i-left+.5)*width_candle

            for tick in range(5):
                yy = y0+h*tick/4
                Color(.18, .24, .34, 1)
                Line(points=[x0,yy,x0+w,yy], width=.65)

            if setup:
                ys,yt = y(setup.bottom),y(setup.top)
                Color(.21,.77,.84,.10)
                Rectangle(pos=(x0,ys),size=(w,max(0,yt-ys)))
                Color(.18,.75,.87,.7)
                Line(points=(x0,ys,x0+w,ys),width=1.2)
                Line(points=(x0,yt,x0+w,yt),width=1.2)

            if self.clusters:
                max_intensity = max([v.intensity for v in self.clusters] or [1.]) or 1.
                for c in self.clusters:
                    Color(1,.44,.18,.12+.65*c.intensity/max_intensity)
                    Line(points=[x0,y(c.price),x0+w,y(c.price)],width=1.0+3*c.intensity/max_intensity)

            for offset,c in enumerate(visible):
                i = left+offset
                color = GREEN if c.close>=c.open else RED
                Color(*color)
                xx=cx(i)
                Line(points=(xx,y(c.low),xx,y(c.high)), width=max(1,dp(.7)))
                bottom=min(c.open,c.close)
                height=max(dp(1.2),abs(y(c.close)-y(c.open)))
                Rectangle(pos=(xx-width_candle*.32,y(bottom)),size=(max(dp(1.3),width_candle*.64),height))

            # EMA is recomputed from the visible historical prefix only.
            full_closes=[c.close for c in self.candles[:right+1]]
            for period,colour in ((20,(.33,.68,.99,1)),(50,(1,.79,.29,1))):
                series=ema(full_closes,period)
                pts=[]
                for index in range(left,right+1):
                    if series[index] is not None:
                        pts.extend((cx(index),max(y0,min(y0+h,y(series[index])))))
                if len(pts)>3:
                    Color(*colour)
                    Line(points=pts,width=1.25)

            if self.frame and self.frame.position:
                p=self.frame.position
                for price,colour in ((p['entry'],TEAL),(p['stop'],RED),(p['target'],GREEN)):
                    Color(*colour)
                    Line(points=(x0,y(price),x0+w,y(price)),width=1.15,dash_length=4,dash_offset=4)
            if self.frame:
                for m in self.frame.markers:
                    idx=m['index']
                    if left<=idx<=right:
                        Color(*(GREEN if m['type']=='entry' else GOLD))
                        xx=cx(idx)
                        yy=y(m['price'])
                        Line(circle=(xx,yy,dp(4)),width=1.8)
                        Line(points=(xx-dp(5),yy,xx+dp(5),yy),width=1.2)


class MainView(BoxLayout):
    def __init__(self, **kwargs):
        super().__init__(orientation='vertical', padding=dp(10),spacing=dp(7),**kwargs)
        self.candles=[]
        self.clusters=[]
        self.session=None
        self.play_clock=None
        self.busy=False
        self.source='Искусственные свечи'
        self._slider_lock=False
        self.validation_report=None

        self.add_widget(label('LIQUIDATION LAB 0.4   |   ВОСПРОИЗВЕДЕНИЕ + ПРОВЕРКА',
                              '20sp', 37, TEAL, True))
        top=BoxLayout(spacing=dp(7),size_hint_y=None,height=dp(41))
        self.mode=spinner('Демо: снижение',('Демо: рост','Демо: снижение','Демо: боковик','Bybit BTCUSDT'),145)
        self.interval=spinner('60',('15','30','60','240','D'),65)
        self.days=spinner('30 дн',('7 дн','30 дн','90 дн'),78)
        top.add_widget(self.mode)
        top.add_widget(label('Таймфрейм',height=41,color=MUTED))
        top.add_widget(self.interval)
        top.add_widget(self.days)
        top.add_widget(button('ЗАГРУЗИТЬ',lambda *_:self.load()))
        self.add_widget(top)

        self.graph=CandleGraph(size_hint_y=.57)
        self.add_widget(self.graph)
        self.price_label=label('График цены · OHLC · EMA 20/50', '12sp', 23, MUTED)
        self.add_widget(self.price_label)

        bar=BoxLayout(spacing=dp(6),size_hint_y=None,height=dp(43))
        bar.add_widget(button('|<',lambda *_:self.seek(0),48))
        bar.add_widget(button('<',lambda *_:self.step(-1),48))
        self.play_button=button('▶',lambda *_:self.toggle_play(),65)
        bar.add_widget(self.play_button)
        bar.add_widget(button('>',lambda *_:self.step(1),48))
        bar.add_widget(button('>|',lambda *_:self.to_end(),48))
        self.speed=spinner('1x',('1x','3x','8x'),58)
        self.speed.bind(text=lambda *_:self.change_speed())
        bar.add_widget(self.speed)
        self.timeline=Slider(min=0,max=1,value=0)
        self.timeline.bind(value=self.on_slider)
        bar.add_widget(self.timeline)
        self.add_widget(bar)

        self.status=label('', '14sp', 31, TEAL, True)
        self.add_widget(self.status)
        self.explain=label('', '12sp', 73, TEXT)
        self.add_widget(self.explain)
        self.journal=label('', '12sp', 72, MUTED)
        self.add_widget(self.journal)

        actions=BoxLayout(spacing=dp(6),size_hint_y=None,height=dp(40))
        actions.add_widget(button('БЭКТЕСТ',lambda *_:self.backtest()))
        actions.add_widget(button('TRAIN / HOLDOUT',lambda *_:self.validate_oos()))
        self.csv_path=TextInput(text='data/bybit_history.csv',multiline=False,font_size='12sp',size_hint_x=2)
        actions.add_widget(self.csv_path)
        actions.add_widget(button('CSV ОТКРЫТЬ',lambda *_:self.load_csv()))
        actions.add_widget(button('CSV СОХР.',lambda *_:self.save_csv()))
        self.add_widget(actions)

        mapping=BoxLayout(spacing=dp(6),size_hint_y=None,height=dp(39))
        self.key=TextInput(hint_text='CoinGlass API key (только для текущей карты)',password=True,
                           multiline=False,font_size='12sp',size_hint_x=3)
        mapping.add_widget(self.key)
        mapping.add_widget(button('КАРТА СЕЙЧАС',lambda *_:self.fetch_map()))
        self.add_widget(mapping)
        self.note=label('Нет реальных ордеров. Карта сейчас скрыта на историческом воспроизведении.',
                        '11sp',26,MUTED)
        self.add_widget(self.note)
        Clock.schedule_once(lambda *_:self.demo(),0)

    def pause(self):
        if self.play_clock is not None:
            self.play_clock.cancel()
            self.play_clock=None
        self.play_button.text='▶'

    def load(self):
        self.pause()
        if self.mode.text.startswith('Демо'):
            self.demo()
        else:
            days=int(self.days.text.split()[0])
            self.run_async(lambda:fetch_bybit_history(interval=self.interval.text,days=days,
                             on_page=lambda n,k:Clock.schedule_once(lambda dt,n=n,k=k:
                             self.set_note(f'Загрузка Bybit: страница {n}, свечей {k}'),0)),
                           lambda result:self.set_data(result,[],'Bybit OHLC · завершённые свечи'))

    def demo(self):
        scenario={'Демо: рост':'up','Демо: снижение':'down','Демо: боковик':'sideways'}.get(self.mode.text,'down')
        candles,clusters=synthetic_scenario(scenario)
        self.set_data(candles,clusters,'Искусственные свечи')

    def set_data(self,candles,clusters,source):
        self.pause()
        self.candles=list(candles)
        self.clusters=list(clusters)
        self.source=source
        self.session=ReplaySession(self.candles)
        self.timeline.max=max(1,len(self.candles)-1)
        self.seek(min(len(self.candles)-1,self.session.warmup))
        self.set_note(f'{source} · {len(self.candles)} свечей · карта не используется в историческом бэктесте')

    def seek(self,index):
        if self.session is None:
            return
        index=max(0,min(int(index),len(self.candles)-1))
        frame=self.session.seek(index)
        self._slider_lock=True
        self.timeline.value=index
        self._slider_lock=False
        self.refresh(frame)

    def step(self,delta):
        self.pause()
        if self.session:
            self.seek(self.session.cursor+delta)

    def to_end(self):
        self.pause()
        if self.session:
            self.seek(len(self.candles)-1)

    def on_slider(self,widget,value):
        if not self._slider_lock and self.session is not None:
            self.pause()
            self.seek(round(value))

    def toggle_play(self):
        if self.play_clock is not None:
            self.pause()
            return
        if self.session is None:return
        if self.session.cursor>=len(self.candles)-1:
            self.seek(0)
        self.play_button.text='II'
        self.change_speed()

    def change_speed(self):
        if self.play_clock is not None:
            self.play_clock.cancel()
            self.play_clock=None
        if self.play_button.text=='II' and self.session:
            speed=int(self.speed.text.replace('x',''))
            self.play_clock=Clock.schedule_interval(self._play_tick,max(.045,.34/speed))

    def _play_tick(self,dt):
        if self.session is None or self.session.cursor >= len(self.candles)-1:
            self.pause()
            return False
        self.seek(self.session.cursor+1)
        return True

    def refresh(self,frame):
        last = frame.index == len(self.candles)-1
        # A present-day heatmap must not leak into historical replay frames.
        overlay=self.clusters if last else []
        self.graph.show(self.candles,frame.index,frame,overlay)
        date=datetime.fromtimestamp(frame.timestamp/1000,timezone.utc).strftime('%d.%m.%Y %H:%M UTC')
        self.price_label.text=(f'{date} | close {frame.price:,.2f} | '
                               f'свеча {frame.index+1}/{len(self.candles)} | OHLC, EMA20/50')
        self.status.text=(f'{frame.phase.upper()}  |  {frame.action}  | '
                          f' equity {frame.equity:,.2f} | просадка {frame.max_drawdown_pct:.2f}%')
        self.explain.text=frame.explanation
        recent=self.session.visible_trades()[-3:]
        self.journal.text=('ЗАКРЫТЫЕ ВИРТУАЛЬНЫЕ СДЕЛКИ: '+str(frame.trade_count)+'\n'+
                           ('\n'.join(f"#{t['opened']}→{t['closed']} {t['side']} {t['reason']}  {t['pnl']:+.2f}"
                                      for t in recent) if recent else 'Сделок пока нет'))
        if self.clusters and not last:
            self.note.text='Текущая/демо карта скрыта: на исторических свечах она могла бы раскрыть будущее.'

    def backtest(self):
        if not self.session:return
        current=self.session.cursor
        self.pause()
        candles=tuple(self.candles)
        def done(out):
            self.seek(current)
            self.set_note(f"БЭКТЕСТ: сделок {out['trade_count']}, доходность {out['return_pct']:+.2f}%, "
                          f"прибыльных {out['win_rate_pct']:.1f}%, max DD {out['max_drawdown_pct']:.2f}% "
                          '(включая плавающую просадку)')
        self.run_async(lambda:simulate(candles),done)

    def validate_oos(self):
        """Independent research holdout; no trading, no live CoinGlass lookahead."""
        if self.busy:
            self.set_note('Сейчас загружаются данные; повторите после завершения.')
            return
        candles=tuple(self.candles)
        if len(candles)<300:
            self.set_note('Для TRAIN/HOLDOUT нужна более длинная история (минимум 300 свечей).')
            return
        self.pause()
        interval=None
        if len(candles)>1:
            interval=int((candles[1].timestamp-candles[0].timestamp)/60000)
        self.run_async(
            lambda: validate_history(candles,source=self.source,
                                     interval_minutes=interval,train_fraction=.70),
            lambda report: self._display_validation(report))

    def _display_validation(self,report):
        self.validation_report=report
        headline=short_summary(report)
        train_n=report['training']['metrics']['trade_count']
        test_n=report['holdout']['metrics']['trade_count']
        sample_warning=('ВНИМАНИЕ: мало сделок в TRAIN/HOLDOUT, оценки нестабильны.\\n'
                        if min(train_n,test_n)<20 else '')
        details=(headline+'\\n\\n'+sample_warning+
                 'Настройки выбраны только по TRAIN. Последние 30% — независимый тест.\\n'
                 'История не содержит исторических карт ликвидаций CoinGlass.\\n\\n'
                 'ОГРАНИЧЕНИЯ:\\n'+'\\n'.join('• '+x for x in report['warnings']))
        self.set_note(f"ПРОВЕРКА 70/30: HOLDOUT {report['holdout']['metrics']['return_pct']:+.2f}%; "
                      f"сделок {test_n}. Экспорт доступен в отчёте.")
        content=BoxLayout(orientation='vertical',spacing=dp(8),padding=dp(10))
        sc=ScrollView()
        lab=Label(text=details,font_size='14sp',color=TEXT,
                  size_hint_y=None,halign='left',valign='top')
        lab.bind(width=lambda w,width:setattr(w,'text_size',(max(dp(200),width-dp(20)),None)))
        lab.bind(texture_size=lambda w,sz:setattr(w,'height',sz[1]+dp(30)))
        sc.add_widget(lab)
        content.add_widget(sc)
        buttons=BoxLayout(size_hint_y=None,height=dp(44),spacing=dp(8))
        buttons.add_widget(button('ЭКСПОРТ JSON + CSV',lambda *_:self.export_oos()))
        popup=Popup(title='VALIDATION 0.4 · CHRONOLOGICAL TRAIN / HOLDOUT',
                    content=content,size_hint=(.88,.86),auto_dismiss=True)
        buttons.add_widget(button('ЗАКРЫТЬ',lambda *_:popup.dismiss(),110))
        content.add_widget(buttons)
        popup.open()

    def export_oos(self):
        if not self.validation_report:
            self.set_note('Сначала выполните TRAIN / HOLDOUT.')
            return
        from pathlib import Path
        stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
        folder=Path('reports')/('validation-'+stamp)
        try:
            folder.mkdir(parents=True,exist_ok=True)
            save_candles_csv(folder/'source_candles.csv',self.candles)
            export_validation(self.validation_report,folder)
            self.set_note('Отчёт JSON/CSV сохранён: '+str(folder.absolute()))
        except Exception as exc:
            self.set_note('Не удалось экспортировать отчёт: '+str(exc))

    def set_note(self,text):
        self.note.text=text

    def run_async(self,func,done):
        if self.busy:
            self.set_note('Подождите завершения текущего запроса')
            return
        self.busy=True
        self.set_note('Запрос данных…')
        def worker():
            try:
                result=func()
            except Exception as exc:
                msg=str(exc)
                Clock.schedule_once(lambda dt: self.on_error(msg),0)
                return
            Clock.schedule_once(lambda dt: self.on_done(done,result),0)
        threading.Thread(target=worker,daemon=True).start()

    def on_done(self,done,result):
        self.busy=False
        done(result)

    def on_error(self,message):
        self.busy=False
        self.set_note('Ошибка загрузки: '+message)

    def load_csv(self):
        try:
            data=load_candles_csv(self.csv_path.text.strip())
            self.set_data(data,[],'Импорт CSV')
        except Exception as exc:
            self.set_note('CSV: '+str(exc))

    def save_csv(self):
        try:
            if not self.candles:
                raise ValueError('Сначала загрузите свечи')
            from pathlib import Path
            path=Path(self.csv_path.text.strip())
            path.parent.mkdir(parents=True,exist_ok=True)
            save_candles_csv(path,self.candles)
            self.set_note('История свечей сохранена: '+str(path))
        except Exception as exc:
            self.set_note('CSV: '+str(exc))

    def fetch_map(self):
        key=self.key.text.strip()
        self.key.text=''
        if not key:
            self.set_note('Для CoinGlass необходим API-ключ с доступом к карте ликвидаций.')
            return
        def done(clusters):
            self.clusters=clusters
            if self.session:
                self.refresh(self.session.seek(self.session.cursor))
            self.set_note('ТЕКУЩАЯ карта CoinGlass загружена ('+str(len(clusters))+
                          ' кластеров). Отображается только на последней свече; не применяется к истории.')
        self.run_async(lambda:fetch_coinglass_snapshot(key),done)


class LiquidationLabApp(App):
    def build(self):
        self.title='Liquidation Lab 0.4 — воспроизведение и проверка'
        Window.clearcolor=(.045,.062,.102,1)
        if Window.system_size[0] < 1040:
            Window.size=(1160,790)
        return MainView()
