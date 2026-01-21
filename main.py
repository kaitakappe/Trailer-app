import wx
import wx.grid
import os
import re
import tempfile
import shutil
import json
import gzip
import inspect
from typing import cast, Optional
try:
	from reportlab.pdfgen import canvas as _pdf_canvas
	from reportlab.lib.pagesizes import A4 as _A4
	from reportlab.pdfbase import pdfmetrics as _pdfmetrics
	from reportlab.pdfbase.ttfonts import TTFont as _TTFont
	_REPORTLAB_AVAILABLE = True
except ImportError:
	_REPORTLAB_AVAILABLE = False

try:
	from PyPDF2 import PdfMerger as _PdfMerger
	_PYPDF2_AVAILABLE = True
except ImportError:
	_PYPDF2_AVAILABLE = False

from lib import (
	compute_weight_metrics,
	calc_braking_force, check_strength, calc_stability_angle,
	stop_distance, parking_brake_total, parking_brake_trailer, running_performance,
	calculate_stability_angle, calc_Lc, calc_R, compute_axle_strength, compute_frame_strength,
	compute_container_frame_strength, compute_container_frame_strength_axles,
	compute_frame_strength_hbeam, compute_container_frame_strength_hbeam, compute_container_frame_strength_axles_hbeam,
	compute_container_frame_strength_supports_inside, compute_container_frame_strength_supports_inside_hbeam,
	compute_hitch_strength, format_hitch_strength_result,
	compute_brake_drum_strength, format_brake_strength_result
)
from lib.form_issuer import (
	Form1Data, Form2Data, collect_calculation_data, auto_fill_form1_data, auto_fill_form2_data, generate_form1_pdf, generate_form2_pdf,
	OverviewData, auto_fill_overview_data, generate_overview_pdf
)
from lib.weight_calculation_sheet import WeightCalculationSheet

RESULT_WINDOW = None

def show_result(title: str, text: str):
	"""結果テキストを共有ウィンドウに表示する。ウィンドウが無ければ生成。"""
	global RESULT_WINDOW
	if RESULT_WINDOW is None or not RESULT_WINDOW:
		RESULT_WINDOW = ResultWindow()
	try:
		if not RESULT_WINDOW.IsShown():
			RESULT_WINDOW.Show()
		RESULT_WINDOW.set_content(title, text)
		RESULT_WINDOW.Raise()
	except RuntimeError:
		# ウィンドウが削除済みの場合、再作成
		RESULT_WINDOW = ResultWindow()
		RESULT_WINDOW.Show()
		RESULT_WINDOW.set_content(title, text)
		RESULT_WINDOW.Raise()


def _open_saved_pdf(path: str):
	"""Windowsで保存したPDFを既定アプリで開く(失敗は無視)。"""
	try:
		os.startfile(path)
	except Exception:
		pass


class ResultWindow(wx.Frame):
	"""計算結果を共有表示するシンプルなウィンドウ。"""

	def __init__(self):
		super().__init__(None, title='計算結果', size=wx.Size(540, 420))
		panel = wx.Panel(self)
		vbox = wx.BoxSizer(wx.VERTICAL)
		self.title_label = wx.StaticText(panel, label='計算結果')
		self.title_label.SetFont(wx.Font(11, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD))
		self.text_ctrl = wx.TextCtrl(panel, style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_RICH2)
		self.text_ctrl.SetFont(wx.Font(9, wx.FONTFAMILY_MODERN, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL))
		vbox.Add(self.title_label, 0, wx.ALL, 6)
		vbox.Add(self.text_ctrl, 1, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 6)
		panel.SetSizer(vbox)
		self.Bind(wx.EVT_CLOSE, self._on_close)

	def set_content(self, title: str, text: str) -> None:
		self.title_label.SetLabel(title)
		self.SetTitle(title)
		self.text_ctrl.SetValue(text)

	def _on_close(self, evt: wx.CloseEvent) -> None:
		# 閉じるではなく非表示にする
		self.Hide()
		evt.Veto()


def create_container_seating_diagram_png(span: float, front: float, rear: float, ax1: float, ax2: float, coupler_off: float) -> str:
	"""コンテナ座配置の簡易図をPNGで返す。"""
	try:
		w, h = 720, 240
		bmp = wx.Bitmap(w, h)
		dc = wx.MemoryDC(bmp)
		dc.SetBackground(wx.Brush(wx.Colour(255, 255, 255)))
		dc.Clear()

		margin = 50
		total = max(span, ax1, ax2, coupler_off + span, front + rear + span)
		if total <= 0:
			total = 100.0
		scale = (w - 2 * margin) / total
		base_y = h // 2 + 30
		to_x = lambda mm: int(margin + mm * scale)

		# ベースラインとコンテナ
		dc.SetPen(wx.Pen(wx.Colour(60, 60, 60), 2))
		dc.DrawLine(to_x(0), base_y, to_x(total), base_y)
		cont_len = max(span, 0.0)
		dc.SetBrush(wx.Brush(wx.Colour(200, 230, 255)))
		dc.SetPen(wx.Pen(wx.Colour(80, 120, 180), 2))
		dc.DrawRectangle(to_x(0), base_y - 70, to_x(cont_len) - to_x(0), 60)
		dc.DrawText('コンテナ', to_x(cont_len / 2) - 20, base_y - 90)

		# 連結部
		dc.SetBrush(wx.Brush(wx.Colour(255, 120, 120)))
		dc.SetPen(wx.Pen(wx.Colour(200, 60, 60), 2))
		cx = to_x(coupler_off)
		dc.DrawCircle(cx, base_y, 7)
		dc.DrawText('連結中心', cx - 22, base_y + 12)

		# 支点位置（前・後）
		dc.SetBrush(wx.Brush(wx.Colour(120, 200, 120)))
		dc.SetPen(wx.Pen(wx.Colour(60, 160, 60), 2))
		fx = to_x(max(front, 0.0))
		rrx = to_x(max(cont_len - rear, 0.0))
		for pos, lbl in [(fx, '前支持'), (rrx, '後支持')]:
			pts = [wx.Point(pos - 7, base_y + 14), wx.Point(pos + 7, base_y + 14), wx.Point(pos, base_y)]
			dc.DrawPolygon(pts)
			dc.DrawText(lbl, pos - 16, base_y + 20)

		# 軸位置
		for pos, lbl in [(ax1, '軸1'), (ax2, '軸2')]:
			if pos <= 0:
				continue
			xp = to_x(pos)
			dc.SetBrush(wx.Brush(wx.Colour(100, 150, 255)))
			dc.SetPen(wx.Pen(wx.Colour(50, 100, 200), 2))
			dc.DrawRectangle(xp - 6, base_y - 6, 12, 12)
			dc.DrawText(lbl, xp - 10, base_y + 20)

		dc.SelectObject(wx.NullBitmap)
		fd, path = tempfile.mkstemp(suffix='.png', prefix='container_seat_')
		os.close(fd)
		bmp.SaveFile(path, wx.BITMAP_TYPE_PNG)
		return path
	except Exception:
		return ''


def create_cross_section_diagram_png(B: float, Hs: float, bb: float, hh: float, tw: float, tf: float, cross_type: str) -> str:
	"""断面形状を簡易描画してPNGパスを返す。"""
	try:
		w, h = 320, 240
		bmp = wx.Bitmap(w, h)
		dc = wx.MemoryDC(bmp)
		dc.SetBackground(wx.Brush(wx.Colour(255, 255, 255)))
		dc.Clear()

		margin = 40
		max_w = max(B, bb if bb > 0 else B, 80)
		max_h = max(Hs, hh if hh > 0 else Hs, 80)
		scale = min((w - 2 * margin) / max_w, (h - 2 * margin) / max_h)
		top = h - margin
		start_x = (w - int(max_w * scale)) // 2

		def px(mm: float) -> int:
			return int(mm * scale)

		# 外枠
		dc.SetPen(wx.Pen(wx.Colour(60, 60, 60), 2))
		dc.SetBrush(wx.TRANSPARENT_BRUSH)
		dc.DrawRectangle(start_x, top - px(Hs), px(B), px(Hs))

		if cross_type == 'hbeam':
			# フランジ
			dc.SetBrush(wx.Brush(wx.Colour(220, 220, 255)))
			dc.DrawRectangle(start_x, top - px(tf), px(B), px(tf))
			dc.DrawRectangle(start_x, top - px(Hs) , px(B), px(tf))
			# ウェブ
			web_w = max(tw, 1.0)
			dc.SetBrush(wx.Brush(wx.Colour(200, 200, 255)))
			dc.DrawRectangle(start_x + px((B - web_w) / 2), top - px(Hs - tf), px(web_w), px(Hs - 2 * tf))
		else:
			# 中空矩形イメージ
			dc.SetBrush(wx.Brush(wx.Colour(230, 230, 230)))
			inner_w = max(bb, B * 0.6)
			inner_h = max(hh, Hs * 0.6)
			dc.DrawRectangle(start_x + px((B - inner_w) / 2), top - px((Hs - inner_h) / 2 + inner_h), px(inner_w), px(inner_h))

		dc.SelectObject(wx.NullBitmap)
		fd, path = tempfile.mkstemp(suffix='.png', prefix='cross_section_')
		os.close(fd)
		bmp.SaveFile(path, wx.BITMAP_TYPE_PNG)
		return path
	except Exception:
		return ''


class SemiTrailerDiagramPanel(wx.Panel):
	"""2軸セミトレーラーの簡易模式図（入力補助）。

	画像ファイルを同梱せず、wxの描画で生成する。
	"""

	def __init__(self, parent, get_values):
		super().__init__(parent, size=wx.Size(-1, 210))
		self._get_values = get_values
		self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
		self.Bind(wx.EVT_PAINT, self._on_paint)

	def refresh(self):
		self.Refresh(False)

	def _on_paint(self, evt):
		dc = wx.AutoBufferedPaintDC(self)
		dc.Clear()
		w, h = self.GetClientSize()

		values = {}
		try:
			values = self._get_values() or {}
		except Exception:
			values = {}

		def f(key):
			v = values.get(key)
			return None if v is None else float(v)

		wb = f('wb')
		a = f('os_a')
		c = f('os_c')
		d = f('os_d')
		b = 0.0
		osv: float | None = None
		if a is not None and c is not None and d is not None:
			a_f = float(a)
			b_f = float(b)
			c_f = float(c)
			d_f = float(d)
			osv = (a_f / 2.0) + b_f - c_f - d_f

		pad = 10
		base_y = int(h * 0.66)
		front_x = pad + 15
		rear_x = w - pad - 15
		body_top = base_y - 45
		body_bottom = base_y - 10

		def draw_dim(
			*,
			x1: int,
			x2: int,
			y: int,
			label: str,
			ref_y1: int | None = None,
			ref_y2: int | None = None,
			pen: wx.Pen | None = None,
		):
			"""簡易寸法線（両矢印＋ラベル＋必要なら補助線）を描く。"""
			if abs(x2 - x1) < 8:
				return
			if pen is None:
				pen = wx.Pen(wx.Colour(0, 0, 0), 1)
			dc.SetPen(pen)

			# 補助線
			if ref_y1 is not None:
				dc.DrawLine(x1, ref_y1, x1, y)
			if ref_y2 is not None:
				dc.DrawLine(x2, ref_y2, x2, y)

			# 寸法線
			dc.DrawLine(x1, y, x2, y)

			# 簡易矢印（端点）
			arrow = 6
			if x2 > x1:
				dc.DrawLine(x1, y, x1 + arrow, y - 4)
				dc.DrawLine(x1, y, x1 + arrow, y + 4)
				dc.DrawLine(x2, y, x2 - arrow, y - 4)
				dc.DrawLine(x2, y, x2 - arrow, y + 4)
			else:
				dc.DrawLine(x1, y, x1 - arrow, y - 4)
				dc.DrawLine(x1, y, x1 - arrow, y + 4)
				dc.DrawLine(x2, y, x2 + arrow, y - 4)
				dc.DrawLine(x2, y, x2 + arrow, y + 4)

			# ラベル
			tw, th = dc.GetTextExtent(label)
			cx = int((x1 + x2) / 2)
			dc.DrawText(label, cx - int(tw / 2), y - th - 2)

		# ペン設定
		dc.SetPen(wx.Pen(wx.Colour(0, 0, 0), 2))
		dc.SetBrush(wx.Brush(wx.Colour(240, 240, 240)))
		# 荷台（長方形）
		dc.DrawRectangle(front_x, body_top, max(10, rear_x - front_x), max(10, body_bottom - body_top))

		# ヒッチカプラー（前方の点）
		kingpin_x = front_x + 18
		dc.SetBrush(wx.Brush(wx.Colour(0, 0, 0)))
		dc.DrawCircle(kingpin_x, body_bottom + 8, 3)
		dc.DrawText('ヒッチカプラー', kingpin_x - 18, body_bottom + 14)

		# 2軸（後方の2つの車輪）
		axle2_x = rear_x - 30
		axle1_x = axle2_x - 38
		wheel_y = body_bottom + 12
		for ax_x in (axle1_x, axle2_x):
			dc.SetBrush(wx.Brush(wx.Colour(255, 255, 255)))
			dc.DrawCircle(ax_x - 10, wheel_y, 8)
			dc.DrawCircle(ax_x + 10, wheel_y, 8)
			dc.SetPen(wx.Pen(wx.Colour(0, 0, 0), 2))
			dc.DrawLine(ax_x, body_bottom, ax_x, wheel_y)
		dc.DrawText('2軸', axle1_x - 6, wheel_y + 10)

		# 寸法線（WB）
		dim_y = body_top - 10
		if w > 200:
			start = kingpin_x
			end = int((axle1_x + axle2_x) / 2)
			label = 'W.B.'
			if wb is not None:
				label += f' = {wb:.0f}mm'
			draw_dim(
				x1=start,
				x2=end,
				y=dim_y,
				label=label,
				ref_y1=body_bottom,
				ref_y2=body_bottom,
			)

		pen_solid = wx.Pen(wx.Colour(0, 0, 0), 1)
		pen_dash = wx.Pen(wx.Colour(0, 0, 0), 1, style=wx.PENSTYLE_SHORT_DASH)
		pen_dot = wx.Pen(wx.Colour(0, 0, 0), 1, style=wx.PENSTYLE_DOT)

		a_label = 'A'
		if a is not None:
			a_label += f' = {a:.0f}mm'
		c_label = 'C'
		if c is not None:
			c_label += f' = {c:.0f}mm'
		d_label = 'D'
		if d is not None:
			d_label += f' = {d:.0f}mm'

		# A: 荷台長さ（前端↔後端）
		y_a = body_top - 34
		draw_dim(
			x1=front_x,
			x2=rear_x,
			y=y_a,
			label=a_label,
			ref_y1=body_top,
			ref_y2=body_top,
			pen=pen_solid,
		)

		# C: 後端↔後軸（後側の区間）
		y_c = body_bottom + 26
		draw_dim(
			x1=axle2_x,
			x2=rear_x,
			y=y_c,
			label=c_label,
			ref_y1=body_bottom,
			ref_y2=body_bottom,
			pen=pen_dash,
		)

		# D: 軸間（2軸間の距離）
		y_d = body_bottom + 60
		draw_dim(
			x1=axle1_x,
			x2=axle2_x,
			y=y_d,
			label=d_label,
			ref_y1=wheel_y,
			ref_y2=wheel_y,
			pen=pen_dash,
		)

		# A/B/C/D と O.S.
		dc.SetPen(wx.Pen(wx.Colour(0, 0, 0), 1))
		text_y = pad
		line1 = 'O.S. = (A/2) - C - D'
		if osv is not None:
			line1 += f' = {osv:.0f}mm'
		dc.DrawText(line1, pad, text_y)
		text_y += 18
		def fmt(name, val):
			return f'{name}={val:.0f}mm' if val is not None else f'{name}=（未入力）'
		dc.DrawText('  '.join([fmt('A', a), fmt('C', c), fmt('D', d)]), pad, text_y)



class WeightCalcPanel(wx.Panel):
	vw: wx.TextCtrl
	ml: wx.TextCtrl
	wb: wx.TextCtrl
	os_a: wx.TextCtrl
	os_c: wx.TextCtrl
	os_d: wx.TextCtrl
	payload_max: wx.TextCtrl
	components_tsv: wx.TextCtrl
	tc: wx.TextCtrl
	tl: wx.TextCtrl
	cw: wx.TextCtrl
	ts_front: wx.TextCtrl
	ts_rear: wx.TextCtrl
	last_data: dict | None
	
	def __init__(self, parent):
		super().__init__(parent)
		v = wx.BoxSizer(wx.VERTICAL)
		v.Add(wx.StaticText(self, label='【計算用入力】（タイヤ強度比・接地圧の計算に使用）'), 0, wx.LEFT|wx.RIGHT|wx.TOP, 6)
		self.vw = self._add(v, '車両重量 [kg]（空車時の総重量）:', '', '2000')
		self.ml = self._add(v, '最大積載量 [kg]（計算用）:', '', '1000')
		v.Add(wx.StaticLine(self), 0, wx.EXPAND|wx.LEFT|wx.RIGHT|wx.TOP|wx.BOTTOM, 6)
		v.Add(
			wx.StaticText(
				self,
				label='【重量計算書(PDF)用入力】（PDF出力ボタンで使用）\n'
				      '・単位は mm / kg です。\n'
				      '・このトレーラーはBオフセット無し（B=0）として扱います。\n'
				      '・O.S.は O.S.=(A/2)−C−D で計算されます。',
			),
			0,
			wx.LEFT|wx.RIGHT|wx.TOP,
			6,
		)
		# セミトレーラー重量計算書（添付様式）用
		self.wb = self._add(v, 'W.B.(ホイールベース) [mm]（軸間距離）:', '', '7850')
		self.payload_max = self._add(v, '最大積載量P [kg]（重量計算書用）:', '', '28000')
		
		self.os_a = self._add(v, 'O.S.用 A [mm]（図面のA。式ではA/2を使用）:', '', '11450')
		self.os_c = self._add(v, 'O.S.用 C [mm]（式では −C）:', '', '1730')
		self.os_d = self._add(v, 'O.S.用 D [mm]（式では −D）:', '', '1360')
		# 入力補助図（2軸セミトレーラー模式図）
		self.diagram = SemiTrailerDiagramPanel(
			self,
			get_values=lambda: {
				'wb': self._safe_float(self.wb.GetValue()),
				'os_a': self._safe_float(self.os_a.GetValue()),
				'os_c': self._safe_float(self.os_c.GetValue()),
				'os_d': self._safe_float(self.os_d.GetValue()),
			},
		)
		v.Add(self.diagram, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 6)
		for ctrl in (self.wb, self.os_a, self.os_c, self.os_d):
			ctrl.Bind(wx.EVT_TEXT, lambda _e: self.diagram.refresh())
		v.Add(
			wx.StaticText(
				self,
				label='部品表（テーブル形式。モーメントは自動計算されます）\n'
				      '・Wi: その部品の重量(kg)（重心に集中荷重として扱います）\n'
				      '・Li: ヒッチカプラー基準の水平方向距離(mm)（前方=マイナス、後方=プラス）\n'
				      '・Hi: 地面基準の高さ(mm)（部品の重心高さ。分からなければ概算でもOK）\n'
				      '・モーメント(Wi×Li、Wi×Hi)は自動計算されます',
			),
			0,
			wx.LEFT|wx.RIGHT|wx.TOP,
			6,
		)
		
		# TSV入力ボタン（互換性のため残す）
		btn_tsv_panel = wx.Panel(self)
		btn_tsv_sizer = wx.BoxSizer(wx.HORIZONTAL)
		btn_import_tsv = wx.Button(btn_tsv_panel, label='TSVからインポート')
		btn_import_tsv.Bind(wx.EVT_BUTTON, self.on_import_tsv)
		btn_tsv_sizer.Add(btn_import_tsv, 0, wx.RIGHT, 8)
		btn_export_tsv = wx.Button(btn_tsv_panel, label='TSVへエクスポート')
		btn_export_tsv.Bind(wx.EVT_BUTTON, self.on_export_tsv)
		btn_tsv_sizer.Add(btn_export_tsv, 0, wx.RIGHT, 8)
		btn_add_row = wx.Button(btn_tsv_panel, label='行追加')
		btn_add_row.Bind(wx.EVT_BUTTON, self.on_add_row)
		btn_tsv_sizer.Add(btn_add_row, 0, wx.RIGHT, 8)
		btn_del_row = wx.Button(btn_tsv_panel, label='選択行削除')
		btn_del_row.Bind(wx.EVT_BUTTON, self.on_delete_row)
		btn_tsv_sizer.Add(btn_del_row, 0)
		btn_tsv_panel.SetSizer(btn_tsv_sizer)
		v.Add(btn_tsv_panel, 0, wx.ALIGN_CENTER|wx.LEFT|wx.RIGHT|wx.TOP, 6)
		
		# グリッドテーブルの作成
		self.components_grid = wx.grid.Grid(self)
		self.components_grid.CreateGrid(10, 7)
		self.components_grid.SetRowLabelSize(40)
		
		# カラムヘッダーの高さを調整（複数行表示のため）
		self.components_grid.SetColLabelSize(60)
		
		# カラムヘッダー設定
		self.components_grid.SetColLabelValue(0, 'No.')
		self.components_grid.SetColLabelValue(1, '名称')
		self.components_grid.SetColLabelValue(2, '重量\nWi\n(kg)')
		self.components_grid.SetColLabelValue(3, 'ヒッチカプラー\nLi\n(mm)')
		self.components_grid.SetColLabelValue(4, 'モーメント\nWi×Li\n(kg·mm)')
		self.components_grid.SetColLabelValue(5, '重心高\nHi\n(mm)')
		self.components_grid.SetColLabelValue(6, 'モーメント\nWi×Hi\n(kg·mm)')
		
		# カラム幅設定
		self.components_grid.SetColSize(0, 50)   # No.
		self.components_grid.SetColSize(1, 150)  # 名称
		self.components_grid.SetColSize(2, 70)   # Wi
		self.components_grid.SetColSize(3, 85)   # Li
		self.components_grid.SetColSize(4, 110)  # Wi×Li（モーメント列を広く）
		self.components_grid.SetColSize(5, 70)   # Hi
		self.components_grid.SetColSize(6, 110)  # Wi×Hi（モーメント列を広く）
		
		# 全セルの背景色とReadOnly属性を設定
		for row in range(self.components_grid.GetNumberRows()):
			# 編集可能な列（0,1,2,3,5）は白背景で編集可能に設定
			for col in [0, 1, 2, 3, 5]:
				self.components_grid.SetReadOnly(row, col, False)
				self.components_grid.SetCellBackgroundColour(row, col, wx.WHITE)
			# モーメント列（4,6）はグレー背景で読み取り専用
			self.components_grid.SetReadOnly(row, 4, True)
			self.components_grid.SetReadOnly(row, 6, True)
			self.components_grid.SetCellBackgroundColour(row, 4, wx.Colour(240, 240, 240))
			self.components_grid.SetCellBackgroundColour(row, 6, wx.Colour(240, 240, 240))
		
		# グリッドのサイズを計算して設定（全列の幅合計 + 行ラベル + スクロールバー余白）
		total_width = sum([self.components_grid.GetColSize(i) for i in range(7)]) + self.components_grid.GetRowLabelSize() + 25
		self.components_grid.SetMinSize(wx.Size(total_width, 300))
		
		# セル編集時のイベントバインド
		self.components_grid.Bind(wx.grid.EVT_GRID_CELL_CHANGED, self.on_grid_cell_changed)
		
		v.Add(self.components_grid, 0, wx.EXPAND|wx.LEFT|wx.RIGHT|wx.BOTTOM, 6)
		
		# 合計表示用ラベル
		self.total_label = wx.StaticText(self, label='合計: Wi=0.0 kg, Wi×Li=0.0 kg·mm, Wi×Hi=0.0 kg·mm')
		self.total_label.SetFont(wx.Font(9, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD))
		v.Add(self.total_label, 0, wx.LEFT|wx.RIGHT|wx.BOTTOM, 6)

		self.tc = self._add(v, 'タイヤ本数:', '', '4')
		self.tl = self._add(v, '推奨荷重/本 [kg]:', '', '600')
		self.cw = self._add(v, '接地幅/本 [cm]:', '', '18')
		# 追加: 前後軸タイヤサイズ入力
		self.ts_front = self._add(v, '前軸タイヤサイズ (インチ可):', '', '11R22.5')
		self.ts_rear = self._add(v, '後軸タイヤサイズ (インチ可):', '', '11R22.5')
		btn_row = wx.BoxSizer(wx.HORIZONTAL)
		btn_calc = wx.Button(self, label='計算')
		btn_calc.Bind(wx.EVT_BUTTON, self.on_calc)
		btn_row.Add(btn_calc, 0, wx.RIGHT, 8)
		btn_pdf = wx.Button(self, label='PDF出力')
		btn_pdf.Bind(wx.EVT_BUTTON, self.on_export_pdf)
		btn_row.Add(btn_pdf, 0)
		v.Add(btn_row, 0, wx.ALIGN_CENTER | wx.ALL, 6)
		# メインウィンドウには結果テキストを表示しない（別ウィンドウのみ）
		self.last_data = None  # 直近計算結果を保持
		self.SetSizer(v)
		self.diagram.refresh()

	def _safe_float(self, s: str) -> float | None:
		try:
			ss = (s or '').strip()
			if not ss:
				return None
			return float(ss)
		except Exception:
			return None

	def _add(self, sizer, label, default='', hint='') -> wx.TextCtrl:
		h = wx.BoxSizer(wx.HORIZONTAL)
		h.Add(wx.StaticText(self, label=label), 0, wx.RIGHT | wx.ALIGN_CENTER_VERTICAL, 6)
		t = wx.TextCtrl(self, value=default, style=wx.TE_RIGHT)
		if hint:
			t.SetHint(hint)
		h.Add(t, 1)
		sizer.Add(h, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, 4)
		return t
	
	def on_grid_cell_changed(self, event):
		"""グリッドセル変更時にモーメントを自動計算"""
		row = event.GetRow()
		col = event.GetCol()
		
		# Wi(col=2), Li(col=3), Hi(col=5)のいずれかが変更されたらモーメントを再計算
		if col in (2, 3, 5):
			self._update_moment_for_row(row)
		
		# 合計を更新
		self._update_totals()
		
		event.Skip()
	
	def _update_moment_for_row(self, row):
		"""指定行のモーメントを計算して更新"""
		try:
			wi_str = self.components_grid.GetCellValue(row, 2)
			li_str = self.components_grid.GetCellValue(row, 3)
			hi_str = self.components_grid.GetCellValue(row, 5)
			
			if wi_str and li_str:
				wi = float(wi_str)
				li = float(li_str)
				moment_li = wi * li
				self.components_grid.SetCellValue(row, 4, f'{moment_li:.0f}')
			else:
				self.components_grid.SetCellValue(row, 4, '')
			
			if wi_str and hi_str:
				wi = float(wi_str)
				hi = float(hi_str)
				moment_hi = wi * hi
				self.components_grid.SetCellValue(row, 6, f'{moment_hi:.0f}')
			else:
				self.components_grid.SetCellValue(row, 6, '')
		except ValueError:
			# 数値に変換できない場合はモーメントをクリア
			self.components_grid.SetCellValue(row, 4, '')
			self.components_grid.SetCellValue(row, 6, '')
	
	def _update_totals(self):
		"""全行の合計を計算して表示"""
		total_wi = 0.0
		total_wi_li = 0.0
		total_wi_hi = 0.0
		
		for row in range(self.components_grid.GetNumberRows()):
			try:
				wi_str = self.components_grid.GetCellValue(row, 2)
				if wi_str:
					wi = float(wi_str)
					total_wi += wi
					
					wi_li_str = self.components_grid.GetCellValue(row, 4)
					if wi_li_str:
						total_wi_li += float(wi_li_str)
					
					wi_hi_str = self.components_grid.GetCellValue(row, 6)
					if wi_hi_str:
						total_wi_hi += float(wi_hi_str)
			except ValueError:
				continue
		
		self.total_label.SetLabelText(
			f'合計: Σ Wi={total_wi:.0f} kg, Σ Wi×Li={total_wi_li:.0f} kg·mm, Σ Wi×Hi={total_wi_hi:.0f} kg·mm'
		)
	
	def on_add_row(self, event):
		"""行を追加"""
		self.components_grid.AppendRows(1)
		row = self.components_grid.GetNumberRows() - 1
		# 編集可能な列は白背景
		for col in [0, 1, 2, 3, 5]:
			self.components_grid.SetReadOnly(row, col, False)
			self.components_grid.SetCellBackgroundColour(row, col, wx.WHITE)
		# モーメント列はグレー背景で読み取り専用
		self.components_grid.SetReadOnly(row, 4, True)
		self.components_grid.SetReadOnly(row, 6, True)
		self.components_grid.SetCellBackgroundColour(row, 4, wx.Colour(240, 240, 240))
		self.components_grid.SetCellBackgroundColour(row, 6, wx.Colour(240, 240, 240))
		self.components_grid.ForceRefresh()
	
	def on_delete_row(self, event):
		"""選択行を削除"""
		selected_rows = self.components_grid.GetSelectedRows()
		if not selected_rows:
			# セルが選択されている場合は、その行を取得
			if self.components_grid.GetGridCursorRow() >= 0:
				selected_rows = [self.components_grid.GetGridCursorRow()]
		
		if selected_rows:
			# 降順でソートして削除（インデックスがずれないように）
			for row in sorted(selected_rows, reverse=True):
				self.components_grid.DeleteRows(row, 1)
			self._update_totals()
			self.components_grid.ForceRefresh()
		else:
			wx.MessageBox('削除する行を選択してください。', '情報', wx.ICON_INFORMATION)
	
	def on_import_tsv(self, event):
		"""TSV形式からグリッドにインポート"""
		dlg = wx.TextEntryDialog(
			self,
			'TSV形式のデータを貼り付けてください：\n'
			'形式: No\t名称\tWi(kg)\tLi(mm)\tHi(mm)\n'
			'例: (1)\tエアカプラカバー\t5\t-700\t1510',
			'TSVインポート',
			style=wx.OK | wx.CANCEL | wx.TE_MULTILINE | wx.TE_WORDWRAP
		)
		dlg.SetSize(500, 400)
		
		if dlg.ShowModal() == wx.ID_OK:
			tsv_text = dlg.GetValue()
			from lib.weight_calculation_sheet import parse_components_tsv
			components = parse_components_tsv(tsv_text)
			
			if components:
				# グリッドをクリア
				for row in range(self.components_grid.GetNumberRows()):
					for col in range(self.components_grid.GetNumberCols()):
						self.components_grid.SetCellValue(row, col, '')
				
				# 必要に応じて行を追加
				current_rows = self.components_grid.GetNumberRows()
				needed_rows = len(components)
				if needed_rows > current_rows:
					self.components_grid.AppendRows(needed_rows - current_rows)
				
				# 全行の背景色とReadOnlyを設定
				for row in range(needed_rows):
					# 編集可能な列は白背景
					for col in [0, 1, 2, 3, 5]:
						self.components_grid.SetReadOnly(row, col, False)
						self.components_grid.SetCellBackgroundColour(row, col, wx.WHITE)
					# モーメント列はグレー背景で読み取り専用
					self.components_grid.SetReadOnly(row, 4, True)
					self.components_grid.SetReadOnly(row, 6, True)
					self.components_grid.SetCellBackgroundColour(row, 4, wx.Colour(240, 240, 240))
					self.components_grid.SetCellBackgroundColour(row, 6, wx.Colour(240, 240, 240))
				
				# データを設定
				for i, comp in enumerate(components):
					self.components_grid.SetCellValue(i, 0, comp.no)
					self.components_grid.SetCellValue(i, 1, comp.name)
					self.components_grid.SetCellValue(i, 2, f'{comp.wi_kg:.0f}')
					self.components_grid.SetCellValue(i, 3, f'{comp.li_mm:.0f}')
					self.components_grid.SetCellValue(i, 5, f'{comp.hi_mm:.0f}')
					self._update_moment_for_row(i)
				
				self._update_totals()
				self.components_grid.ForceRefresh()
				self.components_grid.Refresh()
				wx.CallAfter(self.components_grid.Update)
				wx.MessageBox(f'{len(components)}件のデータをインポートしました。', '完了', wx.ICON_INFORMATION)
			else:
				wx.MessageBox('有効なデータが見つかりませんでした。', 'エラー', wx.ICON_ERROR)
		
		dlg.Destroy()
	
	def on_export_tsv(self, event):
		"""グリッドからTSV形式にエクスポート"""
		lines = ['No\t名称\tWi\tLi\tHi']
		
		for row in range(self.components_grid.GetNumberRows()):
			no = self.components_grid.GetCellValue(row, 0)
			name = self.components_grid.GetCellValue(row, 1)
			wi = self.components_grid.GetCellValue(row, 2)
			li = self.components_grid.GetCellValue(row, 3)
			hi = self.components_grid.GetCellValue(row, 5)
			
			# 空行はスキップ
			if not (no or name or wi or li or hi):
				continue
			
			lines.append(f'{no}\t{name}\t{wi}\t{li}\t{hi}')
		
		tsv_text = '\n'.join(lines)
		
		# クリップボードにコピー
		if wx.TheClipboard.Open():
			wx.TheClipboard.SetData(wx.TextDataObject(tsv_text))
			wx.TheClipboard.Close()
			wx.MessageBox('TSV形式でクリップボードにコピーしました。', '完了', wx.ICON_INFORMATION)
		else:
			wx.MessageBox('クリップボードにアクセスできませんでした。', 'エラー', wx.ICON_ERROR)

	def _get_components_from_grid(self):
		"""グリッドから部品データを取得"""
		from lib.weight_calculation_sheet import SemiTrailerComponent
		components = []
		
		for row in range(self.components_grid.GetNumberRows()):
			no = self.components_grid.GetCellValue(row, 0)
			name = self.components_grid.GetCellValue(row, 1)
			wi_str = self.components_grid.GetCellValue(row, 2)
			li_str = self.components_grid.GetCellValue(row, 3)
			hi_str = self.components_grid.GetCellValue(row, 5)
			
			# 必須項目が空の場合はスキップ
			if not (wi_str and li_str and hi_str):
				continue
			
			try:
				components.append(
					SemiTrailerComponent(
						no=no if no else f'({row+1})',
						name=name if name else '部品',
						wi_kg=float(wi_str),
						li_mm=float(li_str),
						hi_mm=float(hi_str),
					)
				)
			except ValueError:
				continue
		
		return components
	
	def _derive_empty_axle_weights(self) -> tuple[float, float] | None:
		"""部品表+W.B.が揃っている場合、空車時の前軸/後軸重量を導出する。"""
		try:
			components = self._get_components_from_grid()
			wb = float(self.wb.GetValue() or 0)
			if not components or wb <= 0:
				return None
			sheet = WeightCalculationSheet(
				wheelbase_mm=wb,
				payload_max_kg=float(self.payload_max.GetValue() or 0),
				os_a_mm=float(self.os_a.GetValue() or 0),
				os_b_mm=0.0,
				os_c_mm=float(self.os_c.GetValue() or 0),
				os_d_mm=float(self.os_d.GetValue() or 0),
				components=components,
			)
			return (sheet.empty_front_axle_kg(), sheet.empty_rear_axle_kg())
		except Exception:
			return None

	def on_calc(self, _):
		data = None
		error_msgs: list[str] = []
		axle_lines: list[str] = []
		derived_fa_ra: tuple[float, float] | None = None

		try:
			components = self._get_components_from_grid()
			wb = float(self.wb.GetValue() or 0)
			payload_max = float(self.payload_max.GetValue() or 0)
			os_a = float(self.os_a.GetValue() or 0)
			os_b = 0.0
			os_c = float(self.os_c.GetValue() or 0)
			os_d = float(self.os_d.GetValue() or 0)
			if components and wb > 0:
				sheet = WeightCalculationSheet(
					wheelbase_mm=wb,
					payload_max_kg=payload_max,
					os_a_mm=os_a,
					os_b_mm=os_b,
					os_c_mm=os_c,
					os_d_mm=os_d,
					components=components,
				)
				wf0 = sheet.empty_front_axle_kg()
				wr0 = sheet.empty_rear_axle_kg()
				derived_fa_ra = (wf0, wr0)
				osv = sheet.os_mm()
				pf = (payload_max * osv / wb) if wb else 0.0
				wf_loaded = wf0 + pf
				wr_loaded = wr0 + (payload_max - pf)
				L = sheet.cg_l_mm()
				H = sheet.cg_h_mm()
				Lr = float(int((L + 2.5) / 5.0) * 5) if L >= 0 else -float(int(((-L) + 2.5) / 5.0) * 5)
				Hr = float(int((H + 2.5) / 5.0) * 5) if H >= 0 else -float(int(((-H) + 2.5) / 5.0) * 5)
				
				axle_lines = [
					'',
					'◆ 前後軸重量分布（重量計算書ベース）◆',
					f'空車: 前軸 Wf={wf0:.0f}kg  後軸 Wr={wr0:.0f}kg',
					f'積車: 前軸 WF={wf_loaded:.0f}kg  後軸 WR={wr_loaded:.0f}kg',
					f'  → 車両総重量 G.V.W. = {wf_loaded+wr_loaded:.0f}kg',
					f'Pf = P×O.S./W.B. = {pf:.0f}kg  (P={payload_max:.0f}kg, O.S.={osv:.0f}mm, W.B.={wb:.0f}mm)',
					f'重心位置: L={L:.2f}mm ({Lr:.0f}mm)  H={H:.2f}mm ({Hr:.0f}mm)',
				]
			else:
				error_msgs.append('【重量計算書(PDF)用入力】の部品表とW.B.を入力すると、空車時の前後軸重量を自動計算できます。')
		except Exception:
			error_msgs.append('【重量計算書(PDF)用入力】の数値/部品表を確認してください。')

		try:
			vw = float(self.vw.GetValue())
			ml = float(self.ml.GetValue())
			if derived_fa_ra is None:
				derived_fa_ra = self._derive_empty_axle_weights()
			if derived_fa_ra is None:
				raise ValueError('空車時の前後軸重量を導出できません。部品表とW.B.を入力してください。')
			fa, ra = derived_fa_ra
			
			data = compute_weight_metrics(
				vw,
				ml,
				fa,
				ra,
				int(self.tc.GetValue()),
				float(self.tl.GetValue()),
				float(self.cw.GetValue()),
				self.ts_front.GetValue(),
				self.ts_rear.GetValue(),
			)
		except Exception:
			data = None
			error_msgs.append('【計算用入力】の数値を確認してください。（空車時の前後軸重は部品表+W.B.から自動計算します）')

		if data is None and not axle_lines:
			wx.MessageBox('\n'.join(error_msgs) or '入力を確認してください。', '入力エラー', wx.ICON_ERROR)
			return

		lines: list[str] = []
		if data is not None:
			result_lines = [
				'◆ 重量計算結果 ◆',
				f"総重量: {data['total_weight']:.1f} kg",
				f"前軸タイヤ強度比: {data['front_strength_ratio']:.2f}",
				f"後軸タイヤ強度比: {data['rear_strength_ratio']:.2f}",
				f"前軸接地圧（ヒッチ）: {data['front_contact_pressure']:.1f} kg/cm (幅 {data['front_contact_width_cm_used']:.1f} cm)",
			]
			
			# 後軸が2軸の場合、各軸の接地圧を表示
			if 'rear_contact_pressure_1' in data and 'rear_contact_pressure_2' in data:
				result_lines.extend([
					f"後軸1接地圧: {data['rear_contact_pressure_1']:.1f} kg/cm (幅 {data['rear_contact_width_cm_used']:.1f} cm)",
					f"後軸2接地圧: {data['rear_contact_pressure_2']:.1f} kg/cm (幅 {data['rear_contact_width_cm_used']:.1f} cm)",
				])
			else:
				result_lines.append(f"後軸接地圧: {data['rear_contact_pressure']:.1f} kg/cm (幅 {data['rear_contact_width_cm_used']:.1f} cm)")
			
			lines.extend(result_lines)

		lines.extend(axle_lines)
		
		# GUI上に計算結果を表示
		if lines:
			show_result('重量計算結果', '\n'.join(lines))
		
		self.last_data = data if data is not None else {'axle_distribution_only': True}

	def on_export_pdf(self, _):
		if not _REPORTLAB_AVAILABLE:
			wx.MessageBox('ReportLabが未インストールです。インストール後再試行してください。', 'PDF出力不可', wx.ICON_ERROR); return
		with wx.FileDialog(self, message='PDF保存', wildcard='PDF files (*.pdf)|*.pdf', style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT, defaultFile='重量計算書.pdf') as dlg:
			if dlg.ShowModal() != wx.ID_OK:
				return
			path = dlg.GetPath()
		try:
			# 添付様式（セミトレーラー重量計算書）用入力
			components = self._get_components_from_grid()
			if not components:
				wx.MessageBox('部品表が空です。Wi, Li, Hiを入力してください。', '入力不足', wx.ICON_ERROR); return
			wb = float(self.wb.GetValue() or 0)
			payload_max = float(self.payload_max.GetValue() or 0)
			os_a = float(self.os_a.GetValue() or 0)
			os_b = 0.0
			os_c = float(self.os_c.GetValue() or 0)
			os_d = float(self.os_d.GetValue() or 0)
			if wb <= 0:
				wx.MessageBox('W.B.(ホイールベース)[mm] は 0 より大きい数値を入力してください。', '入力エラー', wx.ICON_ERROR); return

			sheet = WeightCalculationSheet(
				wheelbase_mm=wb,
				payload_max_kg=payload_max,
				os_a_mm=os_a,
				os_b_mm=os_b,
				os_c_mm=os_c,
				os_d_mm=os_d,
				components=components,
			)
			
			if sheet.generate_pdf(path):
				_open_saved_pdf(path)
				wx.MessageBox('PDFを保存しました。', '完了', wx.ICON_INFORMATION)
			else:
				wx.MessageBox('PDF生成に失敗しました。', 'エラー', wx.ICON_ERROR)
		except Exception as e:
			wx.MessageBox(f'PDF出力中にエラー: {e}', 'エラー', wx.ICON_ERROR)

	def export_to_path(self, path):
		"""ダイアログ無しで重量計算書PDFを出力"""
		if not _REPORTLAB_AVAILABLE:
			return
		try:
			components = self._get_components_from_grid()
			if not components:
				return
			wb = float(self.wb.GetValue() or 0)
			payload_max = float(self.payload_max.GetValue() or 0)
			os_a = float(self.os_a.GetValue() or 0)
			os_b = 0.0
			os_c = float(self.os_c.GetValue() or 0)
			os_d = float(self.os_d.GetValue() or 0)
			if wb <= 0:
				return
			sheet = WeightCalculationSheet(
				wheelbase_mm=wb,
				payload_max_kg=payload_max,
				os_a_mm=os_a,
				os_b_mm=os_b,
				os_c_mm=os_c,
				os_d_mm=os_d,
				components=components,
			)
			sheet.generate_pdf(path)
		except Exception:
			pass

	def get_state(self) -> dict:
		"""パネルの状態を保存"""
		derived = self._derive_empty_axle_weights()
		fa_s = f"{derived[0]:.0f}" if derived else ''
		ra_s = f"{derived[1]:.0f}" if derived else ''
		
		# グリッドデータを保存
		grid_data = []
		for row in range(self.components_grid.GetNumberRows()):
			row_data = []
			for col in range(self.components_grid.GetNumberCols()):
				row_data.append(self.components_grid.GetCellValue(row, col))
			grid_data.append(row_data)
		
		return {
			'vw': self.vw.GetValue(),
			'ml': self.ml.GetValue(),
			'fa': fa_s,
			'ra': ra_s,
			'wb': self.wb.GetValue(),
			'payload_max': self.payload_max.GetValue(),

			'os_a': self.os_a.GetValue(),
			'os_c': self.os_c.GetValue(),
			'os_d': self.os_d.GetValue(),
			'components_grid': grid_data,
			'tc': self.tc.GetValue(),
			'tl': self.tl.GetValue(),
			'cw': self.cw.GetValue(),
			'ts_front': self.ts_front.GetValue(),
			'ts_rear': self.ts_rear.GetValue(),
			'last_data': self.last_data
		}

	def set_state(self, state: dict) -> None:
		"""パネルの状態を復元"""
		if not state: return
		if 'vw' in state: self.vw.SetValue(str(state['vw']))
		if 'ml' in state: self.ml.SetValue(str(state['ml']))
		if 'wb' in state: self.wb.SetValue(str(state['wb']))
		if 'payload_max' in state: self.payload_max.SetValue(str(state['payload_max']))
		if 'os_a' in state: self.os_a.SetValue(str(state['os_a']))
		if 'os_c' in state: self.os_c.SetValue(str(state['os_c']))
		if 'os_d' in state: self.os_d.SetValue(str(state['os_d']))
		
		# グリッドデータを復元
		if 'components_grid' in state:
			grid_data = state['components_grid']
			if grid_data:
				# バッチ更新開始
				self.components_grid.BeginBatch()
				
				# まず全セルをクリア
				for row in range(self.components_grid.GetNumberRows()):
					for col in range(self.components_grid.GetNumberCols()):
						self.components_grid.SetCellValue(row, col, '')
				
				# 必要に応じて行を追加
				current_rows = self.components_grid.GetNumberRows()
				needed_rows = len(grid_data)
				if needed_rows > current_rows:
					self.components_grid.AppendRows(needed_rows - current_rows)
				
				# データを設定（モーメント列は除く）
				for row_idx, row_data in enumerate(grid_data):
					for col_idx, value in enumerate(row_data):
						if col_idx < self.components_grid.GetNumberCols():
							# モーメント列（4と6）はスキップ（後で再計算）
							if col_idx not in (4, 6):
								self.components_grid.SetCellValue(row_idx, col_idx, str(value) if value else '')
				
				# 全行のモーメントを再計算
				for row_idx in range(len(grid_data)):
					self._update_moment_for_row(row_idx)
				
				# バッチ更新終了
				self.components_grid.EndBatch()
				
				# 列幅を再設定
				self.components_grid.SetColSize(0, 50)
				self.components_grid.SetColSize(1, 150)
				self.components_grid.SetColSize(2, 70)
				self.components_grid.SetColSize(3, 85)
				self.components_grid.SetColSize(4, 110)
				self.components_grid.SetColSize(5, 70)
				self.components_grid.SetColSize(6, 110)
				
				# 全行（初期行含む）の背景色とReadOnlyを再設定
				for row in range(self.components_grid.GetNumberRows()):
					# 編集可能な列（0,1,2,3,5）は白背景に設定
					for col in [0, 1, 2, 3, 5]:
						self.components_grid.SetReadOnly(row, col, False)
						self.components_grid.SetCellBackgroundColour(row, col, wx.WHITE)
					# モーメント列（4,6）はグレー背景で読み取り専用
					self.components_grid.SetReadOnly(row, 4, True)
					self.components_grid.SetReadOnly(row, 6, True)
					self.components_grid.SetCellBackgroundColour(row, 4, wx.Colour(240, 240, 240))
					self.components_grid.SetCellBackgroundColour(row, 6, wx.Colour(240, 240, 240))
				
				self._update_totals()
				self.components_grid.ForceRefresh()
		# 旧形式（TSV）からの移行サポート
		elif 'components_tsv' in state and state['components_tsv']:
			from lib.weight_calculation_sheet import parse_components_tsv
			try:
				components = parse_components_tsv(str(state['components_tsv']))
				if components:
					# バッチ更新開始
					self.components_grid.BeginBatch()
					
					# まず全セルをクリア
					for row in range(self.components_grid.GetNumberRows()):
						for col in range(self.components_grid.GetNumberCols()):
							self.components_grid.SetCellValue(row, col, '')
					
					# 必要に応じて行を追加
					current_rows = self.components_grid.GetNumberRows()
					needed_rows = len(components)
					if needed_rows > current_rows:
						self.components_grid.AppendRows(needed_rows - current_rows)
					
					# データを設定
					for i, comp in enumerate(components):
						self.components_grid.SetCellValue(i, 0, comp.no)
						self.components_grid.SetCellValue(i, 1, comp.name)
						self.components_grid.SetCellValue(i, 2, f'{comp.wi_kg:.0f}')
						self.components_grid.SetCellValue(i, 3, f'{comp.li_mm:.0f}')
						self.components_grid.SetCellValue(i, 5, f'{comp.hi_mm:.0f}')
						self._update_moment_for_row(i)
					
					# バッチ更新終了
					self.components_grid.EndBatch()
					
					# 列幅を再設定
					self.components_grid.SetColSize(0, 50)
					self.components_grid.SetColSize(1, 150)
					self.components_grid.SetColSize(2, 70)
					self.components_grid.SetColSize(3, 85)
					self.components_grid.SetColSize(4, 110)
					self.components_grid.SetColSize(5, 70)
					self.components_grid.SetColSize(6, 110)
					
					# 全行（初期行含む）の背景色とReadOnlyを再設定
					for row in range(self.components_grid.GetNumberRows()):
						# 編集可能な列（0,1,2,3,5）は白背景に設定
						for col in [0, 1, 2, 3, 5]:
							self.components_grid.SetReadOnly(row, col, False)
							self.components_grid.SetCellBackgroundColour(row, col, wx.WHITE)
						# モーメント列（4,6）はグレー背景で読み取り専用
						self.components_grid.SetReadOnly(row, 4, True)
						self.components_grid.SetReadOnly(row, 6, True)
						self.components_grid.SetCellBackgroundColour(row, 4, wx.Colour(240, 240, 240))
						self.components_grid.SetCellBackgroundColour(row, 6, wx.Colour(240, 240, 240))
					
					self._update_totals()
					self.components_grid.ForceRefresh()
			except Exception:
				pass
		
		if 'tc' in state: self.tc.SetValue(str(state['tc']))
		if 'tl' in state: self.tl.SetValue(str(state['tl']))
		if 'cw' in state: self.cw.SetValue(str(state['cw']))
		if 'ts_front' in state: self.ts_front.SetValue(str(state['ts_front']))
		if 'ts_rear' in state: self.ts_rear.SetValue(str(state['ts_rear']))
		if 'last_data' in state: self.last_data = state['last_data']
		# 軸数によって後軸2入力の有効/無効を更新



class HangerLoadDistributionPanel(wx.Panel):
	"""後軸にかかる荷重をリーフスプリングハンガーに分配する計算"""
	
	last_calc_data: Optional[dict]
	
	def __init__(self, parent):
		super().__init__(parent)
		v = wx.BoxSizer(wx.VERTICAL)
		
		# タイトル
		title = wx.StaticText(self, label='リーフスプリング ハンガー及び車軸荷重分配計算')
		f = title.GetFont(); f.PointSize += 2; f = f.Bold(); title.SetFont(f)
		v.Add(title, 0, wx.ALL, 6)
		
		# 説明
		desc = wx.StaticText(self, label=
			'後軸の荷重をリーフスプリングハンガー位置に基づいてモーメント計算し、\n'
			'各ハンガーにかかる荷重を算出します。\n'
			'ハンガー位置はヒッチカプラーからの距離（mm）で指定してください。')
		desc.SetForegroundColour(wx.Colour(60, 60, 60))
		v.Add(desc, 0, wx.ALL, 6)
		
		# 入力セクション
		grid_input = wx.FlexGridSizer(0, 4, 8, 12)
		
		def add_input(label, hint, default=''):
			t = wx.StaticText(self, label=label)
			ctrl = wx.TextCtrl(self, value=default, style=wx.TE_RIGHT)
			hint_text = wx.StaticText(self, label=hint)
			hint_text.SetForegroundColour(wx.Colour(100, 100, 100))
			f_hint = hint_text.GetFont(); f_hint.PointSize -= 1; hint_text.SetFont(f_hint)
			grid_input.Add(t, 0, wx.ALIGN_CENTER_VERTICAL)
			grid_input.Add(ctrl, 1, wx.EXPAND)
			grid_input.Add(hint_text, 0, wx.ALIGN_CENTER_VERTICAL)
			return ctrl
		
		self.rear_axle_empty = add_input('後軸荷重(空車時) [kg]', '空車時の後軸重量', '1800')
		self.rear_axle_loaded = add_input('後軸荷重(積車時) [kg]', '積車時の後軸重量', '2800')
		self.hanger_count = add_input('ハンガー本数', '例: 2本, 4本など', '2')
		grid_input.AddGrowableCol(1, 1); grid_input.AddGrowableCol(3, 1)
		
		box_input = wx.StaticBoxSizer(wx.StaticBox(self, label='基本入力'), wx.VERTICAL)
		box_input.Add(grid_input, 0, wx.EXPAND | wx.ALL, 6)
		v.Add(box_input, 0, wx.EXPAND | wx.ALL, 6)
		
		# ハンガー位置入力テーブル
		v.Add(wx.StaticText(self, label='ハンガー位置（ヒッチカプラーからの距離 mm）'), 0, wx.LEFT|wx.RIGHT|wx.TOP, 12)
		
		self.hanger_grid = wx.grid.Grid(self)
		self.hanger_grid.CreateGrid(6, 2)
		self.hanger_grid.SetColLabelValue(0, 'ハンガー\n番号')
		self.hanger_grid.SetColLabelValue(1, '距離\n(mm)')
		self.hanger_grid.SetColSize(0, 80)
		self.hanger_grid.SetColSize(1, 100)
		self.hanger_grid.SetColLabelSize(40)
		
		# サンプルデータを入力
		sample_distances = [100, 200, 300, 400, 500, 600]
		for row in range(6):
			self.hanger_grid.SetCellValue(row, 0, f'H{row+1}')
			self.hanger_grid.SetCellValue(row, 1, str(sample_distances[row]))
			self.hanger_grid.SetReadOnly(row, 0, True)
			self.hanger_grid.SetCellBackgroundColour(row, 0, wx.Colour(240, 240, 240))
		
		v.Add(self.hanger_grid, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 12)
		
		# ボタン
		h_btn = wx.BoxSizer(wx.HORIZONTAL)
		btn_calc = wx.Button(self, label='計算')
		btn_calc.Bind(wx.EVT_BUTTON, self.on_calc)
		h_btn.Add(btn_calc, 0, wx.RIGHT, 6)
		btn_pdf = wx.Button(self, label='PDF出力')
		btn_pdf.Bind(wx.EVT_BUTTON, self.on_export_pdf)
		h_btn.Add(btn_pdf, 0, wx.RIGHT, 6)
		self.btn_pdf = btn_pdf
		v.Add(h_btn, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 12)
		
		# 結果テーブル
		v.Add(wx.StaticText(self, label='各ハンガーにかかる荷重'), 0, wx.LEFT|wx.RIGHT|wx.TOP, 12)
		
		self.result_grid = wx.grid.Grid(self)
		self.result_grid.CreateGrid(6, 4)
		self.result_grid.SetColLabelValue(0, 'ハンガー\n番号')
		self.result_grid.SetColLabelValue(1, '距離\n(mm)')
		self.result_grid.SetColLabelValue(2, '空車時荷重\n(kg)')
		self.result_grid.SetColLabelValue(3, '積車時荷重\n(kg)')
		self.result_grid.SetColSize(0, 80)
		self.result_grid.SetColSize(1, 100)
		self.result_grid.SetColSize(2, 110)
		self.result_grid.SetColSize(3, 110)
		self.result_grid.SetColLabelSize(40)
		self.result_grid.SetMinSize(wx.Size(-1, 180))  # 最小高さを設定
		
		for row in range(6):
			self.result_grid.SetReadOnly(row, 0, True)
			self.result_grid.SetReadOnly(row, 1, True)
			self.result_grid.SetReadOnly(row, 2, True)
			self.result_grid.SetReadOnly(row, 3, True)
			self.result_grid.SetCellBackgroundColour(row, 0, wx.Colour(240, 240, 240))
			self.result_grid.SetCellBackgroundColour(row, 1, wx.Colour(240, 240, 240))
			self.result_grid.SetCellBackgroundColour(row, 2, wx.Colour(240, 240, 240))
			self.result_grid.SetCellBackgroundColour(row, 3, wx.Colour(240, 240, 240))
		
		v.Add(self.result_grid, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 12)
		
		# 結果テキスト
		self.result_text = wx.TextCtrl(self, style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_WORDWRAP)
		self.result_text.SetMinSize(wx.Size(-1, 180))  # 最小高さを設定
		v.Add(self.result_text, 1, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 12)
		
		# 計算結果を保存する変数
		self.last_calc_data = None
		
		self.SetSizer(v)
	
	def on_calc(self, event):
		"""ハンガー荷重を計算"""
		try:
			# 入力値を取得
			rear_axle_empty = float(self.rear_axle_empty.GetValue() or 0)
			rear_axle_loaded = float(self.rear_axle_loaded.GetValue() or 0)
			hanger_count = int(float(self.hanger_count.GetValue() or 0))
			
			if rear_axle_empty <= 0 or rear_axle_loaded <= 0 or hanger_count <= 0:
				wx.MessageBox('有効な入力をしてください。', '入力エラー', wx.OK | wx.ICON_ERROR)
				return
			
			# ハンガー位置を取得
			distances = []
			for row in range(hanger_count):
				dist_str = self.hanger_grid.GetCellValue(row, 1)
				if dist_str:
					distances.append(float(dist_str))
				else:
					distances.append(0)
			
			if not distances or sum(distances) == 0:
				wx.MessageBox('ハンガー位置を入力してください。', '入力エラー', wx.OK | wx.ICON_ERROR)
				return
			
			# モーメント計算で各ハンガーの荷重を算出
			# 仮定：ハンガーはすべて同じ構造、支点はヒッチカプラー（0mm）と仮定
			# 簡易計算：各ハンガーへの荷重は距離に反比例
			total_moment = sum(distances)
			loads_empty = [rear_axle_empty * d / total_moment for d in distances]
			loads_loaded = [rear_axle_loaded * d / total_moment for d in distances]
			
			# 結果グリッドに表示
			for row in range(hanger_count):
				self.result_grid.SetCellValue(row, 0, f'H{row+1}')
				self.result_grid.SetCellValue(row, 1, f'{distances[row]:.0f}')
				self.result_grid.SetCellValue(row, 2, f'{loads_empty[row]:.1f}')
				self.result_grid.SetCellValue(row, 3, f'{loads_loaded[row]:.1f}')
			
			# 空いている行をクリア
			for row in range(hanger_count, 6):
				self.result_grid.SetCellValue(row, 0, '')
				self.result_grid.SetCellValue(row, 1, '')
				self.result_grid.SetCellValue(row, 2, '')
				self.result_grid.SetCellValue(row, 3, '')
			
			# 結果テキストに表示
			lines = [
				'◆ ハンガー荷重分配計算 ◆',
				'',
				f'空車時 後軸重量: {rear_axle_empty:.1f} kg',
				f'積車時 後軸重量: {rear_axle_loaded:.1f} kg',
				f'ハンガー本数: {hanger_count} 本',
				'',
				'【各ハンガーの荷重】',
			]
			total_load_empty = 0
			total_load_loaded = 0
			for row, (dist, load_e, load_l) in enumerate(zip(distances, loads_empty, loads_loaded)):
				lines.append(f'  H{row+1}: 距離 {dist:.0f} mm → 空車時 {load_e:.1f} kg / 積車時 {load_l:.1f} kg')
				total_load_empty += load_e
				total_load_loaded += load_l
			
			lines.extend([
				'',
				f'各ハンガー荷重の合計:',
				f'  空車時: {total_load_empty:.1f} kg',
				f'  積車時: {total_load_loaded:.1f} kg',
				'',
				'【ハンガーペア間の軸荷重（モーメント平衡計算）】',
			])
			
			# ハンガー同士の中点での軸荷重を計算
			# モーメント平衡を使用：隣接するハンガーペア間で前部・後部の軸荷重を計算
			total_axle_load_empty = 0
			total_axle_load_loaded = 0
			
			for i in range(len(distances) - 1):
				# 隣接する2つのハンガー間のペア
				dist_i = distances[i]
				dist_i1 = distances[i + 1]
				span = dist_i1 - dist_i
				
				if span <= 0:
					continue
				
				# このハンガーペア間に作用する後軸重量の一部を算出
				# 全体の後軸重量をハンガーペア間に分配
				# ハンガーペア間のスパンに基づいて比例配分
				hanger_pair_load_empty = rear_axle_empty * (span / sum(distances[j+1] - distances[j] for j in range(len(distances) - 1))) if len(distances) > 1 else rear_axle_empty
				hanger_pair_load_loaded = rear_axle_loaded * (span / sum(distances[j+1] - distances[j] for j in range(len(distances) - 1))) if len(distances) > 1 else rear_axle_loaded
				
				# モーメント平衡：支点を中点とした時の前部・後部荷重
				midpoint = (dist_i + dist_i1) / 2.0
				dist_to_i = midpoint - dist_i  # 中点からハンガーiまでの距離
				dist_to_i1 = dist_i1 - midpoint  # 中点からハンガーi+1までの距離
				
				# モーメント平衡式：R1 × dist_to_i = R2 × dist_to_i1
				# R1 + R2 = hanger_pair_load
				axle_load_1_empty = hanger_pair_load_empty * dist_to_i1 / (dist_to_i + dist_to_i1)
				axle_load_2_empty = hanger_pair_load_empty * dist_to_i / (dist_to_i + dist_to_i1)
				axle_load_1_loaded = hanger_pair_load_loaded * dist_to_i1 / (dist_to_i + dist_to_i1)
				axle_load_2_loaded = hanger_pair_load_loaded * dist_to_i / (dist_to_i + dist_to_i1)
				
				lines.append(f'  軸{i+1} (H{i+1}～H{i+2}の中点):')
				lines.append(f'    空車時: {axle_load_1_empty:.1f} kg + {axle_load_2_empty:.1f} kg = {axle_load_1_empty + axle_load_2_empty:.1f} kg')
				lines.append(f'    積車時: {axle_load_1_loaded:.1f} kg + {axle_load_2_loaded:.1f} kg = {axle_load_1_loaded + axle_load_2_loaded:.1f} kg')
				total_axle_load_empty += axle_load_1_empty + axle_load_2_empty
				total_axle_load_loaded += axle_load_1_loaded + axle_load_2_loaded
			
			lines.extend([
				'',
				f'合計:',
				f'  空車時: {total_axle_load_empty:.1f} kg',
				f'  積車時: {total_axle_load_loaded:.1f} kg',
			])
			
			self.result_text.SetValue('\n'.join(lines))
			if hasattr(self, 'btn_pdf'):
				self.btn_pdf.Enable(True)
			
			# 計算結果を保存
			self.last_calc_data = {
				'rear_axle_empty': rear_axle_empty,
				'rear_axle_loaded': rear_axle_loaded,
				'hanger_count': hanger_count,
				'distances': distances,
				'loads_empty': loads_empty,
				'loads_loaded': loads_loaded,
				'total_load_empty': total_load_empty,
				'total_load_loaded': total_load_loaded,
				'axle_loads': [],
			}
			
			# 軸荷重データも保存
			for i in range(len(distances) - 1):
				dist_i = distances[i]
				dist_i1 = distances[i + 1]
				span = dist_i1 - dist_i
				if span > 0:
					hanger_pair_load_empty = rear_axle_empty * (span / sum(distances[j+1] - distances[j] for j in range(len(distances) - 1))) if len(distances) > 1 else rear_axle_empty
					hanger_pair_load_loaded = rear_axle_loaded * (span / sum(distances[j+1] - distances[j] for j in range(len(distances) - 1))) if len(distances) > 1 else rear_axle_loaded
					midpoint = (dist_i + dist_i1) / 2.0
					dist_to_i = midpoint - dist_i
					dist_to_i1 = dist_i1 - midpoint
					axle_load_1_empty = hanger_pair_load_empty * dist_to_i1 / (dist_to_i + dist_to_i1)
					axle_load_2_empty = hanger_pair_load_empty * dist_to_i / (dist_to_i + dist_to_i1)
					axle_load_1_loaded = hanger_pair_load_loaded * dist_to_i1 / (dist_to_i + dist_to_i1)
					axle_load_2_loaded = hanger_pair_load_loaded * dist_to_i / (dist_to_i + dist_to_i1)
					self.last_calc_data['axle_loads'].append({
						'index': i + 1,
						'hanger_pair': (i + 1, i + 2),
						'midpoint': midpoint,
						'load_1_empty': axle_load_1_empty,
						'load_2_empty': axle_load_2_empty,
						'total_empty': axle_load_1_empty + axle_load_2_empty,
						'load_1_loaded': axle_load_1_loaded,
						'load_2_loaded': axle_load_2_loaded,
						'total_loaded': axle_load_1_loaded + axle_load_2_loaded,
					})
			
		except Exception as e:
			wx.MessageBox(f'計算中にエラーが発生しました:\n{e}', 'エラー', wx.OK | wx.ICON_ERROR)
	
	def on_export_pdf(self, event):
		"""ハンガー荷重分配計算結果をPDF出力"""
		if not _REPORTLAB_AVAILABLE:
			wx.MessageBox('ReportLabが未インストールです。', 'PDF出力不可', wx.ICON_ERROR)
			return
		
		if not self.last_calc_data:
			wx.MessageBox('先に計算を実行してください。', '計算未実行', wx.ICON_WARNING)
			return
		
		with wx.FileDialog(self, message='PDF保存', wildcard='PDF files (*.pdf)|*.pdf', 
						   style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT, 
						   defaultFile='ハンガー荷重分配計算書.pdf') as dlg:
			if dlg.ShowModal() != wx.ID_OK:
				return
			path = dlg.GetPath()
		
		try:
			self._generate_hanger_load_pdf(path)
			_open_saved_pdf(path)
			wx.MessageBox('PDFを保存しました。', '完了', wx.ICON_INFORMATION)
		except Exception as e:
			wx.MessageBox(f'PDF生成に失敗しました:\n{e}', 'エラー', wx.ICON_ERROR)
	
	def _generate_hanger_load_pdf(self, path: str):
		"""ハンガー荷重分配計算書PDFを生成"""
		from reportlab.pdfgen import canvas as pdf_canvas
		from reportlab.lib.pagesizes import A4
		from reportlab.pdfbase import pdfmetrics
		from reportlab.pdfbase.ttfonts import TTFont
		
		# 日本語フォント登録
		font_name = "JPFont"
		for font_path in [
			"C:/Windows/Fonts/msgothic.ttc",
			"C:/Windows/Fonts/meiryo.ttc",
			"C:/Windows/Fonts/yugothic.ttf",
		]:
			if os.path.exists(font_path):
				try:
					pdfmetrics.registerFont(TTFont(font_name, font_path))
					break
				except:
					pass
		else:
			font_name = "Helvetica"
		
		c = pdf_canvas.Canvas(path, pagesize=A4)
		width, height = A4
		
		data = self.last_calc_data
		if data is None:
			return
		
		# タイトル
		c.setFont(font_name, 16)
		c.drawString(50, height - 50, 'リーフスプリング ハンガー及び車軸荷重分配計算書')
		
		y = height - 90
		c.setFont(font_name, 10)
		
		# 基本情報
		c.drawString(50, y, f"空車時 後軸荷重: {data['rear_axle_empty']:.1f} kg")
		y -= 20
		c.drawString(50, y, f"積車時 後軸荷重: {data['rear_axle_loaded']:.1f} kg")
		y -= 20
		c.drawString(50, y, f"ハンガー本数: {data['hanger_count']} 本")
		y -= 30
		
		# 計算方法の説明
		c.setFont(font_name, 12)
		c.drawString(50, y, '【計算方法】')
		y -= 20
		c.setFont(font_name, 9)
		
		explanation = [
			'1. ハンガー荷重の算出:',
			'   各ハンガーへの荷重は、ヒッチカプラーからの距離に基づいてモーメント計算により算出します。',
			'   計算式: ハンガーi の荷重 = 後軸荷重 × (ハンガーi の距離) / Σ(全ハンガーの距離)',
			'',
			'2. 軸荷重の算出:',
			'   隣接するハンガーペア間の中点での軸荷重を、モーメント平衡により算出します。',
			'   中点位置 = (ハンガーi の距離 + ハンガーi+1 の距離) / 2',
			'   前部荷重 R1: R1 × (中点～ハンガーi の距離) = R2 × (中点～ハンガーi+1 の距離)',
			'   R1 + R2 = ハンガーペア間に作用する荷重',
		]
		
		for line in explanation:
			c.drawString(50, y, line)
			y -= 15
		
		y -= 10
		
		# ハンガー荷重の表
		c.setFont(font_name, 12)
		c.drawString(50, y, '【各ハンガーの荷重】')
		y -= 20
		c.setFont(font_name, 9)
		
		# 表のレイアウト設定
		row_h = 16
		row_count = len(data['distances']) + 1  # データ行 + 合計行
		table_left, table_right = 50, 400
		col_x = [50, 130, 210, 300, 400]
		# ヘッダー行を含む枠を描く
		table_top = y
		table_bottom = table_top - row_h * (row_count + 1)  # +1 はヘッダー行

		# 外枠
		c.line(table_left, table_top, table_right, table_top)
		c.line(table_left, table_bottom, table_right, table_bottom)
		c.line(table_left, table_top, table_left, table_bottom)
		c.line(table_right, table_top, table_right, table_bottom)

		# 縦線（列）
		for x_pos in col_x[1:-1]:
			c.line(x_pos, table_top, x_pos, table_bottom)

		# 横線（各行）
		for idx in range(row_count + 1):  # ヘッダー + データ行
			line_y = table_top - idx * row_h
			c.line(table_left, line_y, table_right, line_y)

		# ヘッダー文字（少し下げて配置）
		header_y = table_top - 11
		c.drawString(60, header_y, 'ハンガー番号')
		c.drawString(140, header_y, '距離 (mm)')
		c.drawString(220, header_y, '空車時 (kg)')
		c.drawString(310, header_y, '積車時 (kg)')

		# データ行
		row_y = table_top - row_h - 11
		for i, (dist, load_e, load_l) in enumerate(zip(data['distances'], data['loads_empty'], data['loads_loaded'])):
			c.drawString(60, row_y, f"H{i+1}")
			c.drawString(140, row_y, f"{dist:.0f}")
			c.drawString(220, row_y, f"{load_e:.1f}")
			c.drawString(310, row_y, f"{load_l:.1f}")
			row_y -= row_h

		# 合計行
		c.drawString(60, row_y, '合計')
		c.drawString(220, row_y, f"{data['total_load_empty']:.1f}")
		c.drawString(310, row_y, f"{data['total_load_loaded']:.1f}")

		y = table_bottom - 20
		y -= 30
		
		# 軸荷重の表
		c.setFont(font_name, 12)
		c.drawString(50, y, '【ハンガーペア間の軸荷重】')
		y -= 20
		c.setFont(font_name, 9)
		y -= 10  # ラベルと表の間に余白を追加
		
		if y < 200:  # スペースが少ない場合は改ページ
			c.showPage()
			y = height - 50
			c.setFont(font_name, 9)
		
		# 表のヘッダー（軸・ハンガーペア・中点・空車・積車）
		c.drawString(60, y, '軸')
		c.drawString(140, y, 'ハンガーペア')
		c.drawString(250, y, '中点(mm)')
		c.drawString(340, y, '空車(kg)')
		c.drawString(430, y, '積車(kg)')
		y -= 13

		# テーブル枠線（ヘッダー＋データ）
		row_h = 16
		row_count = len(data['axle_loads'])
		table_left, table_right = 50, 500
		col_x = [50, 120, 240, 320, 410, 500]
		table_top = y + 10  # ヘッダー上端を少し近づける
		table_bottom = table_top - row_h * row_count

		# 外枠
		c.line(table_left, table_top, table_right, table_top)
		c.line(table_left, table_bottom, table_right, table_bottom)
		c.line(table_left, table_top, table_left, table_bottom)
		c.line(table_right, table_top, table_right, table_bottom)

		# 縦線（列）
		for x_pos in col_x[1:-1]:
			c.line(x_pos, table_top, x_pos, table_bottom)

		# 横線（各行）
		for idx in range(row_count):
			line_y = table_top - (idx + 1) * row_h
			c.line(table_left, line_y, table_right, line_y)

		# データ行
		row_y = table_top - 11
		for axle in data['axle_loads']:
			c.drawString(60, row_y, f"{axle['index']}")
			c.drawString(140, row_y, f"H{axle['hanger_pair'][0]}～H{axle['hanger_pair'][1]}")
			c.drawString(250, row_y, f"{axle['midpoint']:.0f}")
			c.drawString(340, row_y, f"{axle['total_empty']:.1f}")
			c.drawString(430, row_y, f"{axle['total_loaded']:.1f}")
			row_y -= row_h
			if row_y < 100:
				c.showPage()
				y = height - 50
				c.setFont(font_name, 9)
				# 次ページ開始位置を再計算
				table_top = y + 13
				table_bottom = table_top - row_h * (row_count - (data['axle_loads'].index(axle) + 1))
				row_y = table_top - 11
		
		c.save()
	
	def get_state(self) -> dict:
		"""パネルの状態を保存"""
		# ハンガーグリッドのデータを保存
		hanger_data = []
		for row in range(self.hanger_grid.GetNumberRows()):
			row_data = []
			for col in range(self.hanger_grid.GetNumberCols()):
				row_data.append(self.hanger_grid.GetCellValue(row, col))
			hanger_data.append(row_data)
		
		return {
			'rear_axle_empty': self.rear_axle_empty.GetValue(),
			'rear_axle_loaded': self.rear_axle_loaded.GetValue(),
			'hanger_count': self.hanger_count.GetValue(),
			'hanger_data': hanger_data,
		}
	
	def set_state(self, state: dict):
		"""パネルの状態を復元"""
		if not state:
			return
		
		if 'rear_axle_empty' in state:
			self.rear_axle_empty.SetValue(str(state['rear_axle_empty']))
		elif 'hitch_weight' in state:  # 後方互換性のため
			self.rear_axle_empty.SetValue(str(state['hitch_weight']))
		if 'rear_axle_loaded' in state:
			self.rear_axle_loaded.SetValue(str(state['rear_axle_loaded']))
		elif 'hitch_weight' in state:  # 後方互換性のため
			self.rear_axle_loaded.SetValue(str(state['hitch_weight']))
		if 'hanger_count' in state:
			self.hanger_count.SetValue(str(state['hanger_count']))
		
		# ハンガーグリッドのデータを復元
		if 'hanger_data' in state:
			hanger_data = state['hanger_data']
			for row_idx, row_data in enumerate(hanger_data):
				if row_idx < self.hanger_grid.GetNumberRows():
					for col_idx, value in enumerate(row_data):
						if col_idx < self.hanger_grid.GetNumberCols():
							self.hanger_grid.SetCellValue(row_idx, col_idx, str(value) if value else '')


class TireLoadContactPanel(wx.Panel):
	"""タイヤ負荷率及び接地圧計算書（PDF出力専用）。"""

	front_tire_size: wx.TextCtrl
	front_tire_count: wx.TextCtrl
	front_wr_kg: wx.TextCtrl
	front_recommended_per_tire: wx.TextCtrl
	front_install_width_cm: wx.TextCtrl

	rear_tire_size: wx.TextCtrl
	rear_tire_count: wx.TextCtrl
	rear_wr_kg: wx.TextCtrl
	rear_recommended_per_tire: wx.TextCtrl
	rear_install_width_cm: wx.TextCtrl

	def __init__(self, parent):
		super().__init__(parent)
		v = wx.BoxSizer(wx.VERTICAL)
		v.Add(
			wx.StaticText(
				self,
				label='【タイヤ負荷率及び接地圧計算書(PDF)】\n'
				      '例の形式（分数表示＋計算過程）でPDFを出力します。\n'
				      '前軸・後軸の2軸分を同時に出力します。\n'
				      '「重量計算から取得」ボタンで重量計算書のデータを自動反映できます。',
			),
			0,
			wx.LEFT | wx.RIGHT | wx.TOP,
			6,
		)
		
		# 重量計算から取得ボタン
		btn_auto = wx.Button(self, label='重量計算から取得')
		btn_auto.Bind(wx.EVT_BUTTON, self.on_auto_fill_from_weight_calc)
		v.Add(btn_auto, 0, wx.LEFT | wx.RIGHT | wx.TOP, 6)

		def add_section(title: str, defaults: dict[str, str]):
			box = wx.StaticBoxSizer(wx.StaticBox(self, label=title), wx.VERTICAL)
			grid = wx.FlexGridSizer(cols=2, hgap=8, vgap=6)
			grid.AddGrowableCol(1, 1)
			# 対象は固定（前軸/後軸）なので入力は持たない
			grid.Add(wx.StaticText(self, label='タイヤ表記（例: 11R22.5-14PR）:'), 0, wx.ALIGN_CENTER_VERTICAL)
			tire_size = wx.TextCtrl(self, value=defaults.get('tire_size', ''))
			grid.Add(tire_size, 1, wx.EXPAND)

			grid.Add(wx.StaticText(self, label='タイヤ本数 n [本]:'), 0, wx.ALIGN_CENTER_VERTICAL)
			tire_count = wx.TextCtrl(self, value=defaults.get('tire_count', ''), style=wx.TE_RIGHT)
			grid.Add(tire_count, 1, wx.EXPAND)

			grid.Add(wx.StaticText(self, label='軸荷重 Wr [kg]:'), 0, wx.ALIGN_CENTER_VERTICAL)
			wr_kg = wx.TextCtrl(self, value=defaults.get('wr_kg', ''), style=wx.TE_RIGHT)
			grid.Add(wr_kg, 1, wx.EXPAND)

			grid.Add(wx.StaticText(self, label='推奨荷重/本 [kg]:'), 0, wx.ALIGN_CENTER_VERTICAL)
			rec = wx.TextCtrl(self, value=defaults.get('recommended_per_tire', ''), style=wx.TE_RIGHT)
			grid.Add(rec, 1, wx.EXPAND)

			grid.Add(wx.StaticText(self, label='設置幅/本 [cm]:'), 0, wx.ALIGN_CENTER_VERTICAL)
			wcm = wx.TextCtrl(self, value=defaults.get('install_width_cm', ''), style=wx.TE_RIGHT)
			grid.Add(wcm, 1, wx.EXPAND)

			box.Add(grid, 0, wx.EXPAND | wx.ALL, 8)
			v.Add(box, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, 10)
			return tire_size, tire_count, wr_kg, rec, wcm

		(
			self.front_tire_size,
			self.front_tire_count,
			self.front_wr_kg,
			self.front_recommended_per_tire,
			self.front_install_width_cm,
		) = add_section(
			'前軸',
			{
				'tire_size': '11R22.5-14PR',
				'tire_count': '2',
				'wr_kg': '6000',
				'recommended_per_tire': '2500',
				'install_width_cm': '20.0',
			},
		)
		(
			self.rear_tire_size,
			self.rear_tire_count,
			self.rear_wr_kg,
			self.rear_recommended_per_tire,
			self.rear_install_width_cm,
		) = add_section(
			'後軸',
			{
				'tire_size': '11R22.5-14PR',
				'tire_count': '12',
				'wr_kg': '24830',
				'recommended_per_tire': '2500',
				'install_width_cm': '20.0',
			},
		)

		btn_row = wx.BoxSizer(wx.HORIZONTAL)
		btn_pdf = wx.Button(self, label='PDF出力')
		btn_pdf.Bind(wx.EVT_BUTTON, self.on_export_pdf)
		btn_row.Add(btn_pdf, 0)
		v.Add(btn_row, 0, wx.ALIGN_CENTER | wx.ALL, 10)
		self.SetSizer(v)

	def on_auto_fill_from_weight_calc(self, event):
		"""重量計算書から値を自動取得して入力欄に反映"""
		try:
			# MainFrameを通じて重量計算パネルにアクセス
			main_frame = self.GetTopLevelParent()
			weight_panel = getattr(main_frame, 'weight_panel', None)
			if weight_panel is None and hasattr(main_frame, 'panels'):
				for title, panel in getattr(main_frame, 'panels', []):
					if title == '重量計算':
						weight_panel = panel
						break
		
			if weight_panel is None:
				wx.MessageBox('重量計算パネルが見つかりません。', 'エラー', wx.ICON_ERROR)
				return
			
			# 重量計算書のデータを取得
			components = weight_panel._get_components_from_grid()
			wb = float(weight_panel.wb.GetValue() or 0)
			payload_max = float(weight_panel.payload_max.GetValue() or 0)
			os_a = float(weight_panel.os_a.GetValue() or 0)
			os_b = 0.0
			os_c = float(weight_panel.os_c.GetValue() or 0)
			os_d = float(weight_panel.os_d.GetValue() or 0)
			
			if not components or wb <= 0:
				wx.MessageBox('重量計算書の部品表とW.B.を入力してください。', '入力エラー', wx.ICON_WARNING)
				return
			
			from lib.weight_calculation_sheet import WeightCalculationSheet
			sheet = WeightCalculationSheet(
				wheelbase_mm=wb,
				payload_max_kg=payload_max,
				os_a_mm=os_a,
				os_b_mm=os_b,
				os_c_mm=os_c,
				os_d_mm=os_d,
				components=components,
			)
			
			# 空車時の前後軸重量を計算
			wf0 = sheet.empty_front_axle_kg()
			wr0 = sheet.empty_rear_axle_kg()
			
			# 積車時の前後軸重量を計算
			osv = sheet.os_mm()
			pf = (payload_max * osv / wb) if wb else 0.0
			wf_loaded = wf0 + pf
			wr_loaded = wr0 + (payload_max - pf)
			
			# タイヤサイズと基本情報を取得
			tc = weight_panel.tc.GetValue()
			tl = weight_panel.tl.GetValue()
			cw = weight_panel.cw.GetValue()
			ts_front = weight_panel.ts_front.GetValue()
			ts_rear = weight_panel.ts_rear.GetValue()
			
			# タイヤ本数を前後に分配（前軸2本、残りを後軸と仮定）
			try:
				tc_total = int(float(tc or 0))
				front_count = min(2, tc_total)  # 前軸は通常2本
				rear_count = max(0, tc_total - front_count)
			except:
				front_count = 2
				rear_count = 2
			
			# 前軸のデータを設定（積車時重量を使用）
			self.front_tire_size.SetValue(ts_front or '')
			self.front_tire_count.SetValue(str(front_count))
			self.front_wr_kg.SetValue(f'{wf_loaded:.0f}')
			self.front_recommended_per_tire.SetValue(tl or '')
			self.front_install_width_cm.SetValue(cw or '')
			
			# 後軸のデータを設定（積車時重量を使用）
			self.rear_tire_size.SetValue(ts_rear or '')
			self.rear_tire_count.SetValue(str(rear_count))
			self.rear_wr_kg.SetValue(f'{wr_loaded:.0f}')
			self.rear_recommended_per_tire.SetValue(tl or '')
			self.rear_install_width_cm.SetValue(cw or '')
			
			wx.MessageBox(
				f'重量計算書からデータを取得しました。\n'
				f'前軸: {front_count}本, {wf_loaded:.0f}kg (積車時)\n'
				f'後軸: {rear_count}本, {wr_loaded:.0f}kg (積車時)',
				'取得完了',
				wx.ICON_INFORMATION
			)
			
		except Exception as e:
			wx.MessageBox(f'データ取得エラー: {str(e)}', 'エラー', wx.ICON_ERROR)
	
	def _collect_inputs(self):
		def parse_one(prefix: str, label: str, tire_size, tire_count, wr_kg, rec, wcm):
			n = int(float(tire_count.GetValue() or 0))
			wr = float(wr_kg.GetValue() or 0)
			rec_v = float(rec.GetValue() or 0)
			wcm_v = float(wcm.GetValue() or 0)
			if n <= 0:
				raise ValueError(f'{label}: タイヤ本数 n は 1 以上で入力してください。')
			if wr <= 0:
				raise ValueError(f'{label}: Wr は 0 より大きい数値で入力してください。')
			if rec_v <= 0:
				raise ValueError(f'{label}: 推奨荷重/本 は 0 より大きい数値で入力してください。')
			if wcm_v <= 0:
				raise ValueError(f'{label}: 設置幅/本 は 0 より大きい数値で入力してください。')
			return {
				'target_label': label,
				'tire_size_text': tire_size.GetValue(),
				'tire_count_n': n,
				'axle_load_wr_kg': wr,
				'recommended_load_per_tire_kg': rec_v,
				'install_width_per_tire_cm': wcm_v,
			}

		try:
			front = parse_one(
				'front',
				'前輪',
				self.front_tire_size,
				self.front_tire_count,
				self.front_wr_kg,
				self.front_recommended_per_tire,
				self.front_install_width_cm,
			)
			rear = parse_one(
				'rear',
				'後輪',
				self.rear_tire_size,
				self.rear_tire_count,
				self.rear_wr_kg,
				self.rear_recommended_per_tire,
				self.rear_install_width_cm,
			)
			return [front, rear]
		except Exception as e:
			wx.MessageBox(str(e), '入力エラー', wx.ICON_ERROR)
			return None

	def on_export_pdf(self, _):
		if not _REPORTLAB_AVAILABLE:
			wx.MessageBox('ReportLabが未インストールです。インストール後再試行してください。', 'PDF出力不可', wx.ICON_ERROR)
			return
		entries = self._collect_inputs()
		if entries is None:
			return
		with wx.FileDialog(
			self,
			message='PDF保存',
			wildcard='PDF files (*.pdf)|*.pdf',
			style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT,
			defaultFile='タイヤ負荷率及び接地圧計算書.pdf',
		) as dlg:
			if dlg.ShowModal() != wx.ID_OK:
				return
			path = dlg.GetPath()
		try:
			from lib.tire_load_contact_sheet import TireLoadContactSheet, TireLoadContactSheetInput
			sheet = TireLoadContactSheet(
				entries=[TireLoadContactSheetInput(**d) for d in entries],
			)
			if sheet.generate_pdf(path):
				_open_saved_pdf(path)
				wx.MessageBox('PDFを保存しました。', '完了', wx.ICON_INFORMATION)
			else:
				wx.MessageBox('PDF生成に失敗しました。', 'エラー', wx.ICON_ERROR)
		except Exception as e:
			wx.MessageBox(f'PDF出力中にエラー: {e}', 'エラー', wx.ICON_ERROR)

	def export_to_path(self, path: str):
		"""ダイアログ無しでPDFを出力（未入力時は何もしない）。"""
		if not _REPORTLAB_AVAILABLE:
			return
		try:
			# 一括出力では未入力でも止めない
			entries = self._collect_inputs()
			if entries is None:
				return
			from lib.tire_load_contact_sheet import TireLoadContactSheet, TireLoadContactSheetInput
			sheet = TireLoadContactSheet(
				entries=[TireLoadContactSheetInput(**d) for d in entries],
			)
			sheet.generate_pdf(path)
		except Exception:
			return

	def get_state(self) -> dict:
		return {
			'front_tire_size': self.front_tire_size.GetValue(),
			'front_tire_count': self.front_tire_count.GetValue(),
			'front_wr_kg': self.front_wr_kg.GetValue(),
			'front_recommended_per_tire': self.front_recommended_per_tire.GetValue(),
			'front_install_width_cm': self.front_install_width_cm.GetValue(),
			'rear_tire_size': self.rear_tire_size.GetValue(),
			'rear_tire_count': self.rear_tire_count.GetValue(),
			'rear_wr_kg': self.rear_wr_kg.GetValue(),
			'rear_recommended_per_tire': self.rear_recommended_per_tire.GetValue(),
			'rear_install_width_cm': self.rear_install_width_cm.GetValue(),
		}

	def set_state(self, state: dict) -> None:
		if not state:
			return
		try:
			if 'front_tire_size' in state:
				self.front_tire_size.SetValue(str(state['front_tire_size']))
			if 'front_tire_count' in state:
				self.front_tire_count.SetValue(str(state['front_tire_count']))
			if 'front_wr_kg' in state:
				self.front_wr_kg.SetValue(str(state['front_wr_kg']))
			if 'front_recommended_per_tire' in state:
				self.front_recommended_per_tire.SetValue(str(state['front_recommended_per_tire']))
			if 'front_install_width_cm' in state:
				self.front_install_width_cm.SetValue(str(state['front_install_width_cm']))
			if 'rear_tire_size' in state:
				self.rear_tire_size.SetValue(str(state['rear_tire_size']))
			if 'rear_tire_count' in state:
				self.rear_tire_count.SetValue(str(state['rear_tire_count']))
			if 'rear_wr_kg' in state:
				self.rear_wr_kg.SetValue(str(state['rear_wr_kg']))
			if 'rear_recommended_per_tire' in state:
				self.rear_recommended_per_tire.SetValue(str(state['rear_recommended_per_tire']))
			if 'rear_install_width_cm' in state:
				self.rear_install_width_cm.SetValue(str(state['rear_install_width_cm']))
		except Exception:
			return



class CarCalcPanel(wx.Panel):
	def __init__(self, parent):
		super().__init__(parent)
		v = wx.BoxSizer(wx.VERTICAL)
		self.W = self._add(v, '車両総重量 [kg]:', '3000')
		self.Wf = self._add(v, '回転部分重量 [kg]:', '150')
		self.stress = self._add(v, '実応力値:', '120')
		self.allowable = self._add(v, '許容応力値:', '180')
		self.cg = self._add(v, '重心高さ [m]:', '1.2')
		self.tw = self._add(v, 'トレッド幅 [m]:', '1.5')
		h = wx.BoxSizer(wx.HORIZONTAL)
		h.Add(wx.StaticText(self, label='車種区分:'), 0, wx.RIGHT | wx.ALIGN_CENTER_VERTICAL, 6)
		self.car_type = wx.ComboBox(self, choices=['乗用車', 'トラック・バス'], style=wx.CB_READONLY)
		self.car_type.SetSelection(0)
		h.Add(self.car_type, 1)
		v.Add(h, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, 4)
		btn_row = wx.BoxSizer(wx.HORIZONTAL)
		btn_calc = wx.Button(self, label='計算')
		btn_calc.Bind(wx.EVT_BUTTON, self.on_calc)
		btn_row.Add(btn_calc, 0, wx.RIGHT, 8)
		btn_pdf = wx.Button(self, label='PDF出力')
		btn_pdf.Bind(wx.EVT_BUTTON, self.on_export_pdf)
		btn_row.Add(btn_pdf, 0)
		v.Add(btn_row, 0, wx.ALIGN_CENTER | wx.ALL, 6)
		# 結果表示テキストは別ウィンドウのみ
		self.last_values = None
		self.SetSizer(v)

	def _add(self, sizer, label, default=''):
		h = wx.BoxSizer(wx.HORIZONTAL)
		h.Add(wx.StaticText(self, label=label), 0, wx.RIGHT | wx.ALIGN_CENTER_VERTICAL, 6)
		t = wx.TextCtrl(self, value=default, style=wx.TE_RIGHT)
		h.Add(t, 1)
		sizer.Add(h, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, 4)
		return t

	def on_calc(self, _):
		try:
			W = float(self.W.GetValue())
			Wf = float(self.Wf.GetValue())
			stress = float(self.stress.GetValue())
			allowable = float(self.allowable.GetValue())
			cg = float(self.cg.GetValue())
			tw = float(self.tw.GetValue())
			passenger = self.car_type.GetValue() == '乗用車'
		except ValueError:
			wx.MessageBox('数値入力を確認してください。', '入力エラー', wx.ICON_ERROR); return
		F = calc_braking_force(W, Wf, passenger)
		ratio = check_strength(stress, allowable)
		angle = calc_stability_angle(cg, tw)
		coeff = 0.65 if passenger else 0.5
		self.last_values = dict(W=W, Wf=Wf, stress=stress, allowable=allowable, cg=cg, tw=tw,
								 passenger=passenger, coeff=coeff, F=F, ratio=ratio, angle=angle)
		text = '\n'.join([
			'◆ 改造自動車審査計算結果 ◆',
			f'必要制動力: {F:.1f} N',
			f'安全率: {ratio:.2f}',
			f'最大安定傾斜角度: {angle:.2f}°'
		])
		show_result('改造自動車審査計算結果', text)

	def on_export_pdf(self, _):
		if self.last_values is None:
			wx.MessageBox('先に計算を実行してください。', 'PDF出力', wx.ICON_INFORMATION); return
		if not _REPORTLAB_AVAILABLE:
			wx.MessageBox('ReportLabが未インストールです。', 'PDF出力不可', wx.ICON_ERROR); return
		with wx.FileDialog(self, message='PDF保存', wildcard='PDF files (*.pdf)|*.pdf', style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT, defaultFile='改造自動車審査計算書.pdf') as dlg:
			if dlg.ShowModal() != wx.ID_OK: return
			path = dlg.GetPath()
		try:
			c = _pdf_canvas.Canvas(path, pagesize=_A4)
			w, h = _A4
			font = 'Helvetica'
			for f in ['C:/Windows/Fonts/msgothic.ttc', 'C:/Windows/Fonts/meiryo.ttc', 'C:/Windows/Fonts/yugothic.ttf', 'ipaexg.ttf', 'ipaexm.ttf', 'fonts/ipaexg.ttf', 'fonts/ipaexm.ttf']:
				if os.path.exists(f):
					try:
						_pdfmetrics.registerFont(_TTFont('JPFontCM', f))
						font = 'JPFontCM'
						break
					except Exception:
						pass
			v = self.last_values
			# タイトル
			c.setFont(font, 14)
			c.drawString(40, h - 50, '改造自動車審査計算書')
			c.setFont(font, 10)
			start_y = h - 85
			# 入力諸元表
			col_w = [120, 120, 120, 120]
			rows = [
				['項目', '値', '項目', '値'],
				['車両総重量 W (kg)', f"{v['W']:.1f}", '回転部分重量 Wf (kg)', f"{v['Wf']:.1f}"],
				['実応力値', f"{v['stress']:.2f}", '許容応力値', f"{v['allowable']:.2f}"],
				['重心高さ H (m)', f"{v['cg']:.3f}", 'トレッド幅 T (m)', f"{v['tw']:.3f}"],
				['車種区分', '乗用車' if v['passenger'] else 'トラック・バス', '制動係数 k', f"{v['coeff']:.2f}"],
			]
			def table(x, y, cw, rh, data):
				total = sum(cw)
				rows_n = len(data)
				c.rect(x, y - rows_n * rh, total, rows_n * rh)
				cx = x
				for wcol in cw[:-1]:
					cx += wcol
					c.line(cx, y, cx, y - rows_n * rh)
				ry = y
				for _ in range(rows_n - 1):
					ry -= rh
					c.line(x, ry, x + total, ry)
				for r, row in enumerate(data):
					cy = y - (r + 1) * rh + 4
					cx = x + 3
					for i, val in enumerate(row):
						c.drawString(cx, cy, str(val))
						cx += cw[i]
				return y - rows_n * rh - 20
			next_y = table(40, start_y, col_w, 18, rows)
			# 結果サマリ
			results = [
				['必要制動力 F (N)', f"{v['F']:.1f}", '安全率 (許容/実)', f"{v['ratio']:.2f}"],
				['最大安定傾斜角度 θ (°)', f"{v['angle']:.2f}", '', '']
			]
			next_y = table(40, next_y, col_w, 18, [['結果', '', '', '']] + results)
			# 計算式展開
			c.setFont(font, 11)
			y = next_y
			c.drawString(40, y, '(1) 必要制動力 F の計算')
			c.setFont(font, 9)
			c.drawString(55, y - 14, 'F = k × (W + Wf) × 9.8')
			c.drawString(55, y - 28, f"  = {v['coeff']:.2f} × ({v['W']:.1f} + {v['Wf']:.1f}) × 9.8 = {v['F']:.1f} N")
			c.setFont(font, 11)
			y -= 56
			c.drawString(40, y, '(2) 安全率の計算')
			c.setFont(font, 9)
			c.drawString(55, y - 14, '安全率 = 許容応力 / 実応力')
			c.drawString(55, y - 28, f"       = {v['allowable']:.2f} / {v['stress']:.2f} = {v['ratio']:.2f}")
			c.setFont(font, 11)
			y -= 56
			c.drawString(40, y, '(3) 最大安定傾斜角度 θ の計算')
			c.setFont(font, 9)
			c.drawString(55, y - 14, 'tan θ = (T/2) / H  →  θ = arctan((T/2)/H)')
			c.drawString(55, y - 28, f"       = arctan(({v['tw']:.3f}/2)/{v['cg']:.3f}) = {v['angle']:.2f}°")
			# 根拠・考え方
			y -= 16
			c.setFont(font, 11); c.drawString(40, y, '根拠・考え方'); y -= 14; c.setFont(font, 9)
			c.drawString(45, y, '・必要制動力 F は、質量×重力加速度×所要減速度係数に基づく簡易式です。'); y -= 12
			c.drawString(45, y, '・車種区分による係数 k（乗用車0.65/トラック・バス0.5）を想定して評価しています。'); y -= 12
			c.drawString(45, y, '・安定角は、幾何式 tanθ=(T/2)/H を用いて算出しています。')
			c.showPage()
			c.save()
			_open_saved_pdf(path)
			wx.MessageBox('PDFを保存しました。', '完了', wx.ICON_INFORMATION)
		except Exception as e:
			wx.MessageBox(f'PDF出力中エラー: {e}', 'エラー', wx.ICON_ERROR)

	def get_state(self) -> dict:
		return {
			'W': self.W.GetValue(),
			'Wf': self.Wf.GetValue(),
			'stress': self.stress.GetValue(),
			'allowable': self.allowable.GetValue(),
			'cg': self.cg.GetValue(),
			'tw': self.tw.GetValue(),
			'car_type': self.car_type.GetValue(),
			'last_values': self.last_values
		}

	def set_state(self, state: dict) -> None:
		if not state: return
		if 'W' in state: self.W.SetValue(str(state['W']))
		if 'Wf' in state: self.Wf.SetValue(str(state['Wf']))
		if 'stress' in state: self.stress.SetValue(str(state['stress']))
		if 'allowable' in state: self.allowable.SetValue(str(state['allowable']))
		if 'cg' in state: self.cg.SetValue(str(state['cg']))
		if 'tw' in state: self.tw.SetValue(str(state['tw']))
		if 'car_type' in state:
			try:
				idx = self.car_type.FindString(str(state['car_type']))
				if idx != wx.NOT_FOUND:
					self.car_type.SetSelection(idx)
			except Exception:
				pass
		if 'last_values' in state: self.last_values = state['last_values']

	def export_to_path(self, path):
		if self.last_values is None or not _REPORTLAB_AVAILABLE:
			return
		try:
			c = _pdf_canvas.Canvas(path, pagesize=_A4)
			w, h = _A4
			font = 'Helvetica'
			for f in ['C:/Windows/Fonts/msgothic.ttc', 'C:/Windows/Fonts/meiryo.ttc', 'C:/Windows/Fonts/yugothic.ttf', 'ipaexg.ttf', 'ipaexm.ttf', 'fonts/ipaexg.ttf', 'fonts/ipaexm.ttf']:
				if os.path.exists(f):
					try:
						_pdfmetrics.registerFont(_TTFont('JPFontCM', f))
						font = 'JPFontCM'
						break
					except Exception:
						pass
			v = self.last_values
			# タイトル
			c.setFont(font, 14)
			c.drawString(40, h - 50, '改造自動車審査計算書')
			c.setFont(font, 10)
			start_y = h - 85
			# 入力諸元表
			col_w = [120, 120, 120, 120]
			rows = [
				['項目', '値', '項目', '値'],
				['車両総重量 W (kg)', f"{v['W']:.1f}", '回転部分重量 Wf (kg)', f"{v['Wf']:.1f}"],
				['実応力値', f"{v['stress']:.2f}", '許容応力値', f"{v['allowable']:.2f}"],
				['重心高さ H (m)', f"{v['cg']:.3f}", 'トレッド幅 T (m)', f"{v['tw']:.3f}"],
				['車種区分', '乗用車' if v['passenger'] else 'トラック・バス', '制動係数 k', f"{v['coeff']:.2f}"],
			]
			def table(x, y, cw, rh, data):
				total = sum(cw)
				rows_n = len(data)
				c.rect(x, y - rows_n * rh, total, rows_n * rh)
				cx = x
				for wcol in cw[:-1]:
					cx += wcol
					c.line(cx, y, cx, y - rows_n * rh)
				ry = y
				for _ in range(rows_n - 1):
					ry -= rh
					c.line(x, ry, x + total, ry)
				for r, row in enumerate(data):
					cy = y - (r + 1) * rh + 4
					cx = x + 3
					for i, val in enumerate(row):
						c.drawString(cx, cy, str(val))
						cx += cw[i]
				return y - rows_n * rh - 20
			next_y = table(40, start_y, col_w, 18, rows)
			# 結果サマリ
			results = [
				['必要制動力 F (N)', f"{v['F']:.1f}", '安全率 (許容/実)', f"{v['ratio']:.2f}"],
				['最大安定傾斜角度 θ (°)', f"{v['angle']:.2f}", '', '']
			]
			next_y = table(40, next_y, col_w, 18, [['結果', '', '', '']] + results)
			# 計算式展開
			c.setFont(font, 11)
			y = next_y
			c.drawString(40, y, '(1) 必要制動力 F の計算')
			c.setFont(font, 9)
			c.drawString(55, y - 14, 'F = k × (W + Wf) × 9.8')
			c.drawString(55, y - 28, f"  = {v['coeff']:.2f} × ({v['W']:.1f} + {v['Wf']:.1f}) × 9.8 = {v['F']:.1f} N")
			c.setFont(font, 11)
			y -= 56
			c.drawString(40, y, '(2) 安全率の計算')
			c.setFont(font, 9)
			c.drawString(55, y - 14, '安全率 = 許容応力 / 実応力')
			c.drawString(55, y - 28, f"       = {v['allowable']:.2f} / {v['stress']:.2f} = {v['ratio']:.2f}")
			c.setFont(font, 11)
			y -= 56
			c.drawString(40, y, '(3) 最大安定傾斜角度 θ の計算')
			c.setFont(font, 9)
			c.drawString(55, y - 14, 'tan θ = (T/2) / H  →  θ = arctan((T/2)/H)')
			c.drawString(55, y - 28, f"       = arctan(({v['tw']:.3f}/2)/{v['cg']:.3f}) = {v['angle']:.2f}°")
			c.showPage(); c.save()
		except Exception:
			pass


class TrailerSpecPanel(wx.Panel):
	def __init__(self, parent):
		super().__init__(parent)
		# 車両情報 (画像の空欄に合わせた項目)
		info_box = wx.StaticBox(self, label='車両情報')
		info_sizer = wx.StaticBoxSizer(info_box, wx.VERTICAL)
		info_grid = wx.FlexGridSizer(0, 4, 6, 6)
		self.car_name = self._add(info_grid, '車名', '')
		self.model_name = self._add(info_grid, '型式', '')
		self.reg_no = self._add(info_grid, '登録番号', '')
		self.serial_no = self._add(info_grid, 'シリアル番号', '')
		self.body_shape = self._add(info_grid, '車体の形状', '')
		info_grid.AddGrowableCol(1, 1)
		info_grid.AddGrowableCol(3, 1)
		info_sizer.Add(info_grid, 0, wx.EXPAND | wx.ALL, 6)

		# 寸法情報セクション
		dim_box = wx.StaticBox(self, label='寸法情報 (mm)')
		dim_sizer = wx.StaticBoxSizer(dim_box, wx.VERTICAL)
		dim_grid = wx.FlexGridSizer(0, 4, 6, 6)
		self.trailer_length = self._add(dim_grid, '長さ L', '')
		self.trailer_width = self._add(dim_grid, '幅 W', '')
		self.trailer_height = self._add(dim_grid, '高さ H', '')
		self.trailer_wheelbase = self._add(dim_grid, 'ホイールベース', '')
		self.trailer_tread_front = self._add(dim_grid, 'トレッド（前）', '')
		self.trailer_tread_rear = self._add(dim_grid, 'トレッド（後）', '')
		self.trailer_overhang_front = self._add(dim_grid, 'オーバーハング（前）', '')
		self.trailer_overhang_rear = self._add(dim_grid, 'オーバーハング（後）', '')
		dim_grid.AddGrowableCol(1, 1)
		dim_grid.AddGrowableCol(3, 1)
		dim_sizer.Add(dim_grid, 0, wx.EXPAND | wx.ALL, 6)

		grid = wx.FlexGridSizer(0, 4, 6, 6)
		self.W = self._add(grid, '牽引車重量 W', '', '2000')
		self.Wp = self._add(grid, "トレーラ重量 W'", '', '800')
		self.Fm = self._add(grid, '牽引車制動力 Fm', '', '15000')
		self.Fmp = self._add(grid, "慣性制動力 Fm'", '', '8000')
		self.Fs = self._add(grid, '駐車制動力 Fs', '', '1200')
		self.Fsp = self._add(grid, "駐車制動力 Fs'", '', '500')
		self.WD = self._add(grid, '駆動軸重 WD', '', '1200')
		self.PS = self._add(grid, '最高出力 PS', '', '120')
		grid.AddGrowableCol(1, 1); grid.AddGrowableCol(3, 1)
		v = wx.BoxSizer(wx.VERTICAL)
		v.Add(info_sizer, 0, wx.EXPAND | wx.ALL, 6)
		v.Add(dim_sizer, 0, wx.EXPAND | wx.ALL, 6)
		v.Add(grid, 0, wx.EXPAND | wx.ALL, 6)
		btn_row = wx.BoxSizer(wx.HORIZONTAL)
		btn_calc = wx.Button(self, label='判定')
		btn_calc.Bind(wx.EVT_BUTTON, self.on_calc)
		btn_row.Add(btn_calc, 0, wx.RIGHT, 8)
		btn_pdf = wx.Button(self, label='PDF出力')
		btn_pdf.Bind(wx.EVT_BUTTON, self.on_export_pdf)
		btn_row.Add(btn_pdf, 0)
		v.Add(btn_row, 0, wx.ALIGN_CENTER | wx.ALL, 4)
		# 結果は別ウィンドウのみ表示
		self.last_values = None  # 直近計算保持
		self.SetSizer(v)

	def _add(self, sizer, label, default='', hint=''):
		sizer.Add(wx.StaticText(self, label=label), 0, wx.ALIGN_CENTER_VERTICAL)
		t = wx.TextCtrl(self, value=default, size=wx.Size(90, -1), style=wx.TE_RIGHT)
		if hint:
			t.SetHint(hint)
		sizer.Add(t, 0, wx.EXPAND)
		return t

	def on_calc(self, _):
		try:
			W = float(self.W.GetValue()); Wp = float(self.Wp.GetValue())
			Fm = float(self.Fm.GetValue()); Fmp = float(self.Fmp.GetValue())
			Fs = float(self.Fs.GetValue()); Fsp = float(self.Fsp.GetValue())
			WD = float(self.WD.GetValue()); PS = float(self.PS.GetValue())
		except ValueError:
			wx.MessageBox('数値入力を確認してください。', '入力エラー', wx.ICON_ERROR); return
		D, ok_stop, msg_stop = stop_distance(W, Wp, Fm, Fmp)
		ok_pk_total, msg_pk_total = parking_brake_total(W, Wp, Fs)
		ok_pk_tr, msg_pk_tr = parking_brake_trailer(Wp, Fsp)
		ok_run, cond1, cond2, msg_run = running_performance(W, Wp, PS, WD)
		overall = all([ok_stop, ok_pk_total, ok_pk_tr, ok_run])
		self.last_values = dict(W=W, Wp=Wp, Fm=Fm, Fmp=Fmp, Fs=Fs, Fsp=Fsp, WD=WD, PS=PS,
			D=D, ok_stop=ok_stop, msg_stop=msg_stop,
			ok_pk_total=ok_pk_total, msg_pk_total=msg_pk_total,
			ok_pk_tr=ok_pk_tr, msg_pk_tr=msg_pk_tr,
			ok_run=ok_run, cond1=cond1, cond2=cond2, msg_run=msg_run,
			overall=overall)
		text = '\n'.join([
			f"停止距離: {'○' if ok_stop else '×'} {msg_stop}",
			f"駐車ブレーキ(総合): {'○' if ok_pk_total else '×'} {msg_pk_total}",
			f"駐車ブレーキ(トレーラ): {'○' if ok_pk_tr else '×'} {msg_pk_tr}",
			f"走行性能: {'○' if ok_run else '×'} {msg_run} 条件1={cond1} 条件2={cond2}",
			'------------------------------------------',
			f"総合判定: {'○適合' if overall else '×不適合'}"
		])
		show_result('連結仕様計算結果', text)

	def on_export_pdf(self, _):
		if self.last_values is None:
			wx.MessageBox('先に判定計算を実行してください。', 'PDF出力', wx.ICON_INFORMATION); return
		if not _REPORTLAB_AVAILABLE:
			wx.MessageBox('ReportLabが未インストールです。', 'PDF出力不可', wx.ICON_ERROR); return
		with wx.FileDialog(self, message='PDF保存', wildcard='PDF files (*.pdf)|*.pdf', style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT, defaultFile='連結仕様検討書.pdf') as dlg:
			if dlg.ShowModal() != wx.ID_OK: return
			path = dlg.GetPath()
		try:
			c = _pdf_canvas.Canvas(path, pagesize=_A4)
			w, h = _A4
			font = 'Helvetica'
			for f in ['C:/Windows/Fonts/msgothic.ttc', 'C:/Windows/Fonts/meiryo.ttc', 'C:/Windows/Fonts/yugothic.ttf', 'ipaexg.ttf','ipaexm.ttf','fonts/ipaexg.ttf','fonts/ipaexm.ttf']:
				if os.path.exists(f):
					try:
						_pdfmetrics.registerFont(_TTFont('JPFontTS', f)); font='JPFontTS'; break
					except Exception: pass
			vals = self.last_values
			# タイトル
			c.setFont(font, 14)
			c.drawString(40, h-50, 'ライトトレーラ連結仕様検討書')
			# 画像の冒頭空欄に合わせた車両情報を上部に表示（表と重ならないよう余白を拡大）
			try:
				info_y = h - 70
				c.drawString(40, info_y, f"車名: {self.last_values.get('car_name','')}")
				c.drawString(320, info_y, f"型式: {self.last_values.get('model_name','')}")
				c.drawString(40, info_y - 16, f"登録番号: {self.last_values.get('reg_no','')}")
				c.drawString(320, info_y - 16, f"シリアル番号: {self.last_values.get('serial_no','')}")
				c.drawString(40, info_y - 32, f"車体の形状: {self.last_values.get('body_shape','')}")
			except Exception:
				pass
			# 諸元表
			c.setFont(font, 10)
			table_y = h - 120
			col_w = [80, 80, 80, 80, 80, 80]
			labels = ['車両重量 W', 'トレーラ重量 W\'', '牽引車制動力 Fm', '慣性制動力 Fm\'', '駐車制動力 Fs', '駐車制動力 Fs\'']
			values = [vals['W'], vals['Wp'], vals['Fm'], vals['Fmp'], vals['Fs'], vals['Fsp']]
			# 外枠
			width_total = sum(col_w)
			c.rect(40, table_y-40, width_total, 40)
			# ここでは計算済みの vals を使用（再代入はしない）
			cx = 40
			for wcol in col_w[:-1]:
				cx += wcol
				c.line(cx, table_y, cx, table_y-40)
			# 横線中央
			c.line(40, table_y-20, 40+width_total, table_y-20)
			# テキスト
			c.setFont(font,9)
			cx = 40
			for i, lab in enumerate(labels):
				c.drawString(cx+3, table_y-12, lab)
				cx += col_w[i]
			cx = 40
			for i, val in enumerate(values):
				c.drawRightString(cx+col_w[i]-4, table_y-32, f"{val:.0f}")
				cx += col_w[i]
			# 追加諸元行 (WD, PS)
			c.drawString(40, table_y-58, f"駆動軸重 WD: {vals['WD']:.0f}")
			c.drawString(200, table_y-58, f"最高出力 PS: {vals['PS']:.0f}")
			# 第2タイトル
			c.setFont(font, 12)
			c.drawString(40, table_y-90, 'ライト・トレーラの連結仕様検討計算書')
			c.setFont(font, 10)
			start_y = table_y-110
			line_gap = 14
			# 各判定出力
			def mark(ok): return '○' if ok else '×'
			lines = [
				f"(1) 停止距離: {mark(vals['ok_stop'])} {vals['msg_stop']}",
				f"(2) 駐車ブレーキ(総合): {mark(vals['ok_pk_total'])} {vals['msg_pk_total']}",
				f"(3) 駐車ブレーキ(トレーラ): {mark(vals['ok_pk_tr'])} {vals['msg_pk_tr']}",
				f"(4) 走行性能 条件1={vals['cond1']} 条件2={vals['cond2']} 判定: {mark(vals['ok_run'])} {vals['msg_run']}",
				f"(5) 総合判定: {mark(vals['overall'])} {'適合' if vals['overall'] else '不適合'}"
			]
			y = start_y
			for ln in lines:
				c.drawString(40, y, ln); y -= line_gap
			# 計算式展開セクション
			c.setFont(font, 11)
			formula_y = y - 10
			# 明示キャストで型警告抑止
			W = cast(float, vals['W']); Wp = cast(float, vals['Wp']); Fm = cast(float, vals['Fm']); Fmp = cast(float, vals['Fmp']); Fs = cast(float, vals['Fs']); Fsp = cast(float, vals['Fsp']); WD = cast(float, vals['WD']); PS = cast(float, vals['PS'])
			GCW = W + Wp
			# 1) 停止距離 D 式
			speed_kmh = 50.0; margin = 1.05; threshold = 25.0
			speed_ms = speed_kmh * (1000.0/3600.0)
			D = ((W + Wp) * margin * speed_ms) / (Fm + Fmp) if (Fm+Fmp)>0 else 0.0
			c.drawString(40, formula_y, '停止距離 D の計算式')
			c.setFont(font, 9)
			c.drawString(55, formula_y-14, f"D = ((W + W') × {margin} × (50×1000/3600)) / (Fm + Fm')")
			c.drawString(55, formula_y-28, f"  = (({W:.0f} + {Wp:.0f}) × {margin} × {speed_ms:.2f}) / ({Fm:.0f} + {Fmp:.0f})")
			c.drawString(55, formula_y-42, f"  = {D:.2f} m ≦ {threshold:.0f} m → {'適' if D<=threshold else '否'}")
			# 2) 駐車ブレーキ総合 Fs 判定
			c.setFont(font,11)
			pb_y = formula_y-70
			req_total = (W + Wp) * 0.2
			c.drawString(40, pb_y, '駐車ブレーキ(総合) 判定式')
			c.setFont(font,9)
			c.drawString(55, pb_y-14, "必要制動力 = (W + W') × 0.2")
			c.drawString(55, pb_y-28, f"            = ({W:.0f} + {Wp:.0f}) × 0.2 = {req_total:.1f}")
			c.drawString(55, pb_y-42, f"Fs = {Fs:.1f} → {'適' if Fs>=req_total else '否'}")
			# 3) 駐車ブレーキ(トレーラ) 判定
			tr_y = pb_y-70
			req_tr = Wp * 0.2
			c.setFont(font,11)
			c.drawString(40, tr_y, '駐車ブレーキ(トレーラ) 判定式')
			c.setFont(font,9)
			c.drawString(55, tr_y-14, "必要制動力 = W' × 0.2")
			c.drawString(55, tr_y-28, f"            = {Wp:.0f} × 0.2 = {req_tr:.1f}")
			c.drawString(55, tr_y-42, f"Fs' = {Fsp:.1f} → {'適' if Fsp>=req_tr else '否'}")
			# 4) 走行性能 条件式
			run_y = tr_y-70
			cond1_lhs = 121.0*PS - 1900.0
			cond2_lhs = 4.0*WD
			c.setFont(font,11)
			c.drawString(40, run_y, '走行性能条件')
			c.setFont(font,9)
			c.drawString(55, run_y-14, "条件1: 121×PS - 1900 > GCW")
			c.drawString(55, run_y-28, f"        {121.0:.0f}×{PS:.0f} - 1900 = {cond1_lhs:.0f} > {GCW:.0f} → {'適' if cond1_lhs>GCW else '否'}")
			c.drawString(55, run_y-42, "条件2: 4×WD > GCW")
			c.drawString(55, run_y-56, f"        4×{WD:.0f} = {cond2_lhs:.0f} > {GCW:.0f} → {'適' if cond2_lhs>GCW else '否'}")
			overall = cond1_lhs>GCW and cond2_lhs>GCW and Fs>=req_total and Fsp>=req_tr and D<=threshold
			c.drawString(55, run_y-74, f"総合: {'適合' if overall else '不適合'}")
			c.showPage(); c.save(); _open_saved_pdf(path); wx.MessageBox('PDFを保存しました。', '完了', wx.ICON_INFORMATION)
		except Exception as e:
			wx.MessageBox(f'PDF出力中エラー: {e}', 'エラー', wx.ICON_ERROR)

	def get_state(self):
		return {
			'car_name': self.car_name.GetValue(),
			'model_name': self.model_name.GetValue(),
			'reg_no': self.reg_no.GetValue(),
			'serial_no': self.serial_no.GetValue(),
			'body_shape': self.body_shape.GetValue(),
			'trailer_length': self.trailer_length.GetValue(),
			'trailer_width': self.trailer_width.GetValue(),
			'trailer_height': self.trailer_height.GetValue(),
			'trailer_wheelbase': self.trailer_wheelbase.GetValue(),
			'trailer_tread_front': self.trailer_tread_front.GetValue(),
			'trailer_tread_rear': self.trailer_tread_rear.GetValue(),
			'trailer_overhang_front': self.trailer_overhang_front.GetValue(),
			'trailer_overhang_rear': self.trailer_overhang_rear.GetValue(),
			'W': self.W.GetValue(),
			'Wp': self.Wp.GetValue(),
			'Fm': self.Fm.GetValue(),
			'Fmp': self.Fmp.GetValue(),
			'Fs': self.Fs.GetValue(),
			'Fsp': self.Fsp.GetValue(),
			'WD': self.WD.GetValue(),
			'PS': self.PS.GetValue(),
			'last_values': self.last_values,
		}

	def set_state(self, state):
		if not state: return
		if 'car_name' in state: self.car_name.SetValue(str(state['car_name']))
		if 'model_name' in state: self.model_name.SetValue(str(state['model_name']))
		if 'reg_no' in state: self.reg_no.SetValue(str(state['reg_no']))
		if 'serial_no' in state: self.serial_no.SetValue(str(state['serial_no']))
		if 'body_shape' in state: self.body_shape.SetValue(str(state['body_shape']))
		if 'trailer_length' in state: self.trailer_length.SetValue(str(state['trailer_length']))
		if 'trailer_width' in state: self.trailer_width.SetValue(str(state['trailer_width']))
		if 'trailer_height' in state: self.trailer_height.SetValue(str(state['trailer_height']))
		if 'trailer_wheelbase' in state: self.trailer_wheelbase.SetValue(str(state['trailer_wheelbase']))
		if 'trailer_tread_front' in state: self.trailer_tread_front.SetValue(str(state['trailer_tread_front']))
		if 'trailer_tread_rear' in state: self.trailer_tread_rear.SetValue(str(state['trailer_tread_rear']))
		if 'trailer_overhang_front' in state: self.trailer_overhang_front.SetValue(str(state['trailer_overhang_front']))
		if 'trailer_overhang_rear' in state: self.trailer_overhang_rear.SetValue(str(state['trailer_overhang_rear']))
		if 'W' in state: self.W.SetValue(str(state['W']))
		if 'Wp' in state: self.Wp.SetValue(str(state['Wp']))
		if 'Fm' in state: self.Fm.SetValue(str(state['Fm']))
		if 'Fmp' in state: self.Fmp.SetValue(str(state['Fmp']))
		if 'Fs' in state: self.Fs.SetValue(str(state['Fs']))
		if 'Fsp' in state: self.Fsp.SetValue(str(state['Fsp']))
		if 'WD' in state: self.WD.SetValue(str(state['WD']))
		if 'PS' in state: self.PS.SetValue(str(state['PS']))
		if 'last_values' in state: self.last_values = state['last_values']

	def export_to_path(self, path):
		if self.last_values is None or not _REPORTLAB_AVAILABLE:
			return
		try:
			c = _pdf_canvas.Canvas(path, pagesize=_A4)
			w, h = _A4
			font = 'Helvetica'
			for f in ['C:/Windows/Fonts/msgothic.ttc', 'C:/Windows/Fonts/meiryo.ttc', 'C:/Windows/Fonts/yugothic.ttf', 'ipaexg.ttf','ipaexm.ttf','fonts/ipaexg.ttf','fonts/ipaexm.ttf']:
				if os.path.exists(f):
					try:
						_pdfmetrics.registerFont(_TTFont('JPFontTS', f)); font='JPFontTS'; break
					except Exception: pass
			vals = self.last_values
			# タイトル
			c.setFont(font, 14)
			c.drawString(40, h-50, 'ライトトレーラ連結仕様検討書')
			# 車両情報
			try:
				info_y = h - 70
				c.drawString(40, info_y, f"車名: {self.last_values.get('car_name','')}")
				c.drawString(320, info_y, f"型式: {self.last_values.get('model_name','')}")
				c.drawString(40, info_y - 16, f"登録番号: {self.last_values.get('reg_no','')}")
				c.drawString(320, info_y - 16, f"シリアル番号: {self.last_values.get('serial_no','')}")
				c.drawString(40, info_y - 32, f"車体の形状: {self.last_values.get('body_shape','')}")
			except Exception:
				pass
			# 諸元表
			c.setFont(font, 10)
			table_y = h - 120
			col_w = [80, 80, 80, 80, 80, 80]
			labels = ['車両重量 W', "トレーラ重量 W'", '牽引車制動力 Fm', "慣性制動力 Fm'", '駐車制動力 Fs', "駐車制動力 Fs'"]
			values = [vals['W'], vals['Wp'], vals['Fm'], vals['Fmp'], vals['Fs'], vals['Fsp']]
			width_total = sum(col_w)
			c.rect(40, table_y-40, width_total, 40)
			cx = 40
			for wcol in col_w[:-1]:
				cx += wcol
				c.line(cx, table_y, cx, table_y-40)
			c.line(40, table_y-20, 40+width_total, table_y-20)
			c.setFont(font,9)
			cx = 40
			for i, lab in enumerate(labels):
				c.drawString(cx+3, table_y-12, lab)
				cx += col_w[i]
			cx = 40
			for i, val in enumerate(values):
				c.drawRightString(cx+col_w[i]-4, table_y-32, f"{val:.0f}")
				cx += col_w[i]
			c.drawString(40, table_y-58, f"駆動軸重 WD: {vals['WD']:.0f}")
			c.drawString(200, table_y-58, f"最高出力 PS: {vals['PS']:.0f}")
			# 判定セクション
			c.setFont(font, 12)
			c.drawString(40, table_y-90, 'ライト・トレーラの連結仕様検討計算書')
			c.setFont(font, 10)
			start_y = table_y-110
			line_gap = 14
			def mark(ok): return '○' if ok else '×'
			lines = [
				f"(1) 停止距離: {mark(vals['ok_stop'])} {vals['msg_stop']}",
				f"(2) 駐車ブレーキ(総合): {mark(vals['ok_pk_total'])} {vals['msg_pk_total']}",
				f"(3) 駐車ブレーキ(トレーラ): {mark(vals['ok_pk_tr'])} {vals['msg_pk_tr']}",
				f"(4) 走行性能 条件1={vals['cond1']} 条件2={vals['cond2']} 判定: {mark(vals['ok_run'])} {vals['msg_run']}",
				f"(5) 総合判定: {mark(vals['overall'])} {'適合' if vals['overall'] else '不適合'}"
			]
			y = start_y
			for ln in lines:
				c.drawString(40, y, ln); y -= line_gap
			# 計算式展開
			c.setFont(font, 11)
			formula_y = y - 10
			W = cast(float, vals['W']); Wp = cast(float, vals['Wp']); Fm = cast(float, vals['Fm']); Fmp = cast(float, vals['Fmp']); Fs = cast(float, vals['Fs']); Fsp = cast(float, vals['Fsp']); WD = cast(float, vals['WD']); PS = cast(float, vals['PS'])
			D = cast(float, vals['D'])
			c.drawString(40, formula_y, '主要式:')
			c.setFont(font, 9)
			formula_lines = [
				f"GCW = W + W' = {W:.0f} + {Wp:.0f} = {W+Wp:.0f}",
				f"停止距離: 条件に基づく判定 → {vals['msg_stop']}",
				f"駐車(総合): Fs >= 1.5×GCW? → {vals['msg_pk_total']}",
				f"駐車(トレーラ): Fs' >= 0.18×W'? → {vals['msg_pk_tr']}",
				f"走行性能: 3×PS > GCW, 4×WD > GCW → {vals['msg_run']}",
				f"D = PS/GCW×1000 = {PS:.0f}/{(W+Wp):.0f}×1000 = {D:.2f}"
			]
			for ln in formula_lines:
				c.drawString(40, formula_y-14, ln); formula_y -= 14
			# 根拠・考え方
			y = formula_y - 6
			c.setFont(font, 11); c.drawString(40, y, '根拠・考え方'); y -= 14; c.setFont(font, 9)
			c.drawString(45, y, '・停止距離は、想定する制動力と合成重量の釣合いから簡易に評価しています。'); y -= 12
			c.drawString(45, y, '・駐車制動は、総合=1.5×GCW 以上、トレーラ=0.18×W\' 以上の目安で判定しています。'); y -= 12
			c.drawString(45, y, '・走行性能は 3×PS>GCW, 4×WD>GCW の簡易基準により動力余裕を確認します。'); y -= 12
			c.drawString(45, y, '・指数 D=PS/GCW×1000 は出力と重量の比を表す指標で、しきい値以下を目安とします。')
			c.showPage(); c.save()
		except Exception:
			pass


class StabilityAnglePanel(wx.Panel):
	def __init__(self, parent):
		super().__init__(parent)
		v = wx.BoxSizer(wx.VERTICAL)

		# 図の表示 (diagram.png / diafram.png の順で探索)
		img_path_candidates = ['diagram.png', 'diafram.png']
		bitmap_added = False
		for p in img_path_candidates:
			if os.path.exists(p):
				try:
					img = wx.Image(p, wx.BITMAP_TYPE_ANY)
					max_w = 850
					if img.GetWidth() > max_w:
						scale = max_w / img.GetWidth()
						img = img.Scale(max_w, int(img.GetHeight() * scale))
					# 1.1倍拡大（品質維持のため最後に適用）
					enlarge = 1.1
					enlarged_w = int(img.GetWidth() * enlarge)
					enlarged_h = int(img.GetHeight() * enlarge)
					img = img.Scale(enlarged_w, enlarged_h)
					bmp = wx.StaticBitmap(self, bitmap=wx.BitmapBundle.FromBitmap(wx.Bitmap(img)))
					v.Add(bmp, 0, wx.ALIGN_CENTER | wx.ALL, 6)
					bitmap_added = True
					break
				except Exception:
					continue
		if not bitmap_added:
			v.Add(wx.StaticText(self, label='(図ファイル未検出: diagram.png)'), 0, wx.ALIGN_CENTER | wx.ALL, 6)

		# 入力欄 (トラクタ諸元 / トレーラ諸元) を左右に分割
		self.inputs = {}
		row_gap = 4
		col_gap = 6
		tractor_box = wx.StaticBox(self, label='トラクタ諸元')
		trailer_box = wx.StaticBox(self, label='トレーラ諸元')
		tractor_sizer = wx.StaticBoxSizer(tractor_box, wx.VERTICAL)
		trailer_sizer = wx.StaticBoxSizer(trailer_box, wx.VERTICAL)

		tractor_grid = wx.FlexGridSizer(0, 2, row_gap, col_gap)
		trailer_grid = wx.FlexGridSizer(0, 2, row_gap, col_gap)

		tractor_fields = [
			('W1', '車両重量 W₁ (kg)'),
			('W1f', '前軸重量 W₁f (kg)'),
			('W1r', '後軸重量 W₁r (kg)'),
			('T1f', '前輪輪距 T₁f (m)'),
			('T1r', '後輪輪距(最外側) T₁r (m)'),
			('H1', '重心高 H₁ (m)'),
		]

		trailer_fields = [
			('W2', '車両重量 W₂ (kg)'),
			('W2f', '第5輪重量2f₂f (kg)'),
			('W2r', '後軸重量 W₂ (kg)'),
			('T2f', 'ヒッチカプラー安 T2f₂f (m)'),
			('T2r', '後輪輪距(最外側) r₂r (m)'),
			('H2', '重心高 H₂ (m)')
		]

		for key, label in tractor_fields:
			tractor_grid.Add(wx.StaticText(self, label=label), 0, wx.ALIGN_CENTER_VERTICAL)
			t = wx.TextCtrl(self, value='', size=wx.Size(90, -1), style=wx.TE_RIGHT)
			t.SetHint('0.0')
			self.inputs[key] = t
			tractor_grid.Add(t, 0, wx.EXPAND)

		for key, label in trailer_fields:
			trailer_grid.Add(wx.StaticText(self, label=label), 0, wx.ALIGN_CENTER_VERTICAL)
			t = wx.TextCtrl(self, value='', size=wx.Size(90, -1), style=wx.TE_RIGHT)
			t.SetHint('0.0')
			self.inputs[key] = t
			trailer_grid.Add(t, 0, wx.EXPAND)

		tractor_grid.AddGrowableCol(1, 1)
		trailer_grid.AddGrowableCol(1, 1)

		tractor_sizer.Add(tractor_grid, 0, wx.EXPAND | wx.ALL, 6)
		trailer_sizer.Add(trailer_grid, 0, wx.EXPAND | wx.ALL, 6)

		groups_h = wx.BoxSizer(wx.HORIZONTAL)
		groups_h.Add(tractor_sizer, 1, wx.EXPAND | wx.RIGHT, 6)
		groups_h.Add(trailer_sizer, 1, wx.EXPAND | wx.LEFT, 6)
		v.Add(groups_h, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, 6)
		# ボタン行: 計算 / PDF出力
		btn_row = wx.BoxSizer(wx.HORIZONTAL)
		btn_calc=wx.Button(self,label='安定角計算')
		btn_calc.Bind(wx.EVT_BUTTON,self.on_calc)
		btn_row.Add(btn_calc,0,wx.RIGHT,8)
		btn_pdf=wx.Button(self,label='PDF出力')
		btn_pdf.Bind(wx.EVT_BUTTON,self.on_export_pdf)
		btn_row.Add(btn_pdf,0)
		v.Add(btn_row,0,wx.ALIGN_CENTER|wx.ALL,4)
		# 結果は ResultWindow のみ
		self.last_inputs = None
		self.last_res = None
		self.SetSizer(v)

	def on_calc(self,_):
		data = {}
		try:
			for k, ctrl in self.inputs.items():
				data[k] = float(ctrl.GetValue())
		except ValueError:
			wx.MessageBox('数値入力を確認してください。', '入力エラー', wx.ICON_ERROR); return
		res = calculate_stability_angle(data)
		if not res:
			wx.MessageBox('計算失敗', 'エラー', wx.ICON_ERROR); return
		self.last_inputs = data
		self.last_res = res
		text = '\n'.join([
			'◆ 最大安定傾斜角度計算結果 ◆',
			f"B1 = {res.get('B1',0):.4f} m",
			f"B2 = {res.get('B2',0):.4f} m",
			f"B  = {res.get('B',0):.4f} m",
			f"H  = {res.get('H',0):.4f} m",
			f"θ1 = {res.get('theta1',0):.4f}°"
		])
		show_result('最大安定傾斜角度計算結果', text)

	def on_export_pdf(self,_):
		if self.last_inputs is None or self.last_res is None:
			wx.MessageBox('先に安定角計算を実行してください。', 'PDF出力', wx.ICON_INFORMATION); return
		if not _REPORTLAB_AVAILABLE:
			wx.MessageBox('ReportLabが未インストールです。', 'PDF出力不可', wx.ICON_ERROR); return
		with wx.FileDialog(self, message='PDF保存', wildcard='PDF files (*.pdf)|*.pdf', style=wx.FD_SAVE|wx.FD_OVERWRITE_PROMPT, defaultFile='最大安定傾斜角度計算書.pdf') as dlg:
			if dlg.ShowModal()!=wx.ID_OK: return
			path = dlg.GetPath()
		try:
			c = _pdf_canvas.Canvas(path, pagesize=_A4)
			W,H = _A4
			font='Helvetica'
			for f in ['C:/Windows/Fonts/msgothic.ttc', 'C:/Windows/Fonts/meiryo.ttc', 'C:/Windows/Fonts/yugothic.ttf', 'ipaexg.ttf','ipaexm.ttf','fonts/ipaexg.ttf','fonts/ipaexm.ttf']:
				if os.path.exists(f):
					try:
						_pdfmetrics.registerFont(_TTFont('JPStab',f)); font='JPStab'; break
					except Exception: pass
			
			left = 40; y = H - 40
			c.setFont(font,12)
			c.drawString(left, y, '最大安定傾斜角度計算書（セミ・トレーラ連結車）')
			y -= 24
			
			# (1) 連結時の安定幅：B
			c.setFont(font,10)
			y -= 18
			
			# 図の挿入（diagram.png または diafram.png があれば）
			img_inserted = False
			for img_name in ['diagram.png', 'diafram.png']:
				if os.path.exists(img_name):
					try:
						img_w = 640; img_h = 200
						c.drawImage(img_name, left - 70, y - img_h, width=img_w, height=img_h, preserveAspectRatio=True, mask='auto')
						y -= img_h + 10
						img_inserted = True
						break
					except Exception:
						pass
			if not img_inserted:
				y -= 10
			
			# ① 諸元 - 左右2列の表
			c.setFont(font,9)
			c.drawText(c.beginText(left, y))
			
			# 表の定義：左側トラクタ、右側トレーラ
			W1 = self.last_inputs['W1']; W1f = self.last_inputs['W1f']; W1r = self.last_inputs['W1r']
			T1f = self.last_inputs['T1f']; T1r = self.last_inputs['T1r']; H1 = self.last_inputs['H1']
			W2 = self.last_inputs['W2']; W2f = self.last_inputs['W2f']; W2r = self.last_inputs['W2r']
			T2f = self.last_inputs['T2f']; T2r = self.last_inputs['T2r']; H2 = self.last_inputs['H2']
			
			# 2列表示用のヘルパー
			def draw_side_by_side_tables(x_start, y_start, left_data, right_data, left_title, right_title):
				"""左右に並べた表を描画"""
				table_w = 250; table_h = 18; title_h = 18
				# 左側表
				x_l = x_start
				c.rect(x_l, y_start - title_h - table_h * len(left_data), table_w, title_h + table_h * len(left_data))
				c.setFont(font, 9)
				c.drawString(x_l + 4, y_start - 12, left_title)
				c.line(x_l, y_start - title_h, x_l + table_w, y_start - title_h)
				# 左側の縦線（3列：項目、値、単位）
				c.line(x_l + 130, y_start - title_h, x_l + 130, y_start - title_h - table_h * len(left_data))
				c.line(x_l + 200, y_start - title_h, x_l + 200, y_start - title_h - table_h * len(left_data))
				# 左側の横線
				for i in range(1, len(left_data)):
					c.line(x_l, y_start - title_h - table_h * i, x_l + table_w, y_start - title_h - table_h * i)
				# 左側データ
				c.setFont(font, 8)
				for i, (label, val, unit) in enumerate(left_data):
					cy = y_start - title_h - table_h * (i + 1) + 6
					c.drawString(x_l + 4, cy, label)
					c.drawRightString(x_l + 195, cy, val)
					c.drawString(x_l + 205, cy, unit)
				
				# 右側表
				x_r = x_start + table_w + 10
				c.rect(x_r, y_start - title_h - table_h * len(right_data), table_w, title_h + table_h * len(right_data))
				c.setFont(font, 9)
				c.drawString(x_r + 4, y_start - 12, right_title)
				c.line(x_r, y_start - title_h, x_r + table_w, y_start - title_h)
				# 右側の縦線
				c.line(x_r + 130, y_start - title_h, x_r + 130, y_start - title_h - table_h * len(right_data))
				c.line(x_r + 200, y_start - title_h, x_r + 200, y_start - title_h - table_h * len(right_data))
				# 右側の横線
				for i in range(1, len(right_data)):
					c.line(x_r, y_start - title_h - table_h * i, x_r + table_w, y_start - title_h - table_h * i)
				# 右側データ
				c.setFont(font, 8)
				for i, (label, val, unit) in enumerate(right_data):
					cy = y_start - title_h - table_h * (i + 1) + 6
					c.drawString(x_r + 4, cy, label)
					c.drawRightString(x_r + 195, cy, val)
					c.drawString(x_r + 205, cy, unit)
				
				return y_start - title_h - table_h * max(len(left_data), len(right_data)) - 12
			
			left_data = [
				('車両重量', f"W₁", f"({W1:.1f})", 'kg'),
				('前軸重量', f"W₁f", f"({W1f:.1f})", 'kg'),
				('後軸重量', f"W₁r", f"({W1r:.1f})", 'kg'),
				('前輪輪距', f"T₁f", f"({T1f:.3f})", 'm'),
				('後輪輪距(最外側)', f"T₁r", f"({T1r:.3f})", 'm'),
				('重心高', f"H₁", f"({H1:.3f})", 'm'),
			]
			
			right_data = [
				('車両重量', f"W₂", f"({W2:.1f})", 'kg'),
				('第5輪重量', f"W₂f", f"({W2f:.1f})", 'kg'),
				('後軸重量', f"W₂r", f"({W2r:.1f})", 'kg'),
				('ヒッチカプラー安定幅 T₂f = T₁r', f"({T2f:.3f})", 'm'),
				('後輪輪距(最外側)', f"T₂r", f"({T2r:.3f})", 'm'),
				('重心高', f"H₂", f"({H2:.3f})", 'm'),
			]
			
			# 簡易版：項目、値（記号付き）、単位の3列表示
			left_simple = [
				(f'車両重量  W₁', f"{W1:.1f}", 'kg'),
				(f'前軸重量  W₁f', f"{W1f:.1f}", 'kg'),
				(f'後軸重量  W₁r', f"{W1r:.1f}", 'kg'),
				(f'前輪輪距  T₁f', f"{T1f:.3f}", 'm'),
				(f'後輪輪距(最外側) T₁r', f"{T1r:.3f}", 'm'),
				(f'重心高  H₁', f"{H1:.3f}", 'm'),
			]
			
			right_simple = [
				(f'車両重量  W₂', f"{W2:.1f}", 'kg'),
				(f'第5輪重量  W₂f', f"{W2f:.1f}", 'kg'),
				(f'後軸重量  W₂r', f"{W2r:.1f}", 'kg'),
				(f'ヒッチカプラー安定幅 T₂f = T₁r', f"{T2f:.3f}", 'm'),
				(f'後輪輪距(最外側) T₂r', f"{T2r:.3f}", 'm'),
				(f'重心高  H₂', f"{H2:.3f}", 'm'),
			]
			
			y = draw_side_by_side_tables(left, y, left_simple, right_simple, 'トラクタ諸元', 'トレーラ諸元')
			
			# ② トラクタ安定幅：B₁
			B1 = self.last_res.get('B1', 0)
			c.setFont(font, 9)
			c.drawString(left, y, f"②  トラクタ安定幅：B₁      (m)")
			y -= 16
			c.setFont(font, 8)
			c.drawString(left + 20, y, f"B₁ = (W₁f・T₁f + W₁r・T₁r) / (2・W₁) = ({W1f:.1f}×{T1f:.3f} + {W1r:.1f}×{T1r:.3f}) / (2×{W1:.1f}) = {B1:.4f}  m")
			y -= 18
			
			# ③ トレーラ安定幅：B₂
			B2 = self.last_res.get('B2', 0)
			c.setFont(font, 9)
			c.drawString(left, y, f"③  トレーラ安定幅：B₂      (m)")
			y -= 16
			c.setFont(font, 8)
			c.drawString(left + 20, y, f"B₂ = (W₂f・T₂f + W₂r・T₂r) / (2・W₂) = ({W2f:.1f}×{T2f:.3f} + {W2r:.1f}×{T2r:.3f}) / (2×{W2:.1f}) = {B2:.4f}  m")
			y -= 18
			
			# ④ 連結時安定幅：B
			B = self.last_res.get('B', 0)
			c.setFont(font, 9)
			c.drawString(left, y, f"④  連結時安定幅：B         (m)")
			y -= 16
			c.setFont(font, 8)
			c.drawString(left + 20, y, f"B = (W₁・B₁ + W₂・B₂) / (W₁ + W₂) = ({W1:.1f}×{B1:.4f} + {W2:.1f}×{B2:.4f}) / ({W1:.1f}+{W2:.1f}) = {B:.4f}  m")
			y -= 18
			
			# (2) 連結時の重心高：H
			c.setFont(font, 10)
			c.drawString(left, y, '(2)  連結時の重心高：H      (m)')
			y -= 16
			Hc = self.last_res.get('H', 0)
			c.setFont(font, 8)
			c.drawString(left + 20, y, f"H = (H₁・W₁ + H₂・W₂) / (W₁ + W₂) = ({H1:.3f}×{W1:.1f} + {H2:.3f}×{W2:.1f}) / ({W1:.1f}+{W2:.1f}) = {Hc:.4f}  m")
			y -= 18
			
			# (3) 連結時の最大安定傾斜角度：θ₁
			theta = self.last_res.get('theta1', 0)
			c.setFont(font, 10)
			c.drawString(left, y, '(3)  連結時の最大安定傾斜角度：β')
			y -= 16
			c.setFont(font, 8)
			c.drawString(left + 20, y, f"tan θ₁ = B / H = {B:.4f} / {Hc:.4f} = {(B/Hc if Hc>0 else 0):.4f}")
			y -= 14
			c.drawString(left + 20, y, f"θ₁ = {theta:.2f}°≧35°")
			y -= 10
			
			c.showPage(); c.save(); _open_saved_pdf(path); wx.MessageBox('PDFを保存しました。', '完了', wx.ICON_INFORMATION)
		except Exception as e:
			wx.MessageBox(f'PDF出力中エラー: {e}', 'エラー', wx.ICON_ERROR)

	def get_state(self):
		state = {}
		for key, ctrl in self.inputs.items():
			state[key] = ctrl.GetValue()
		state['last_inputs'] = self.last_inputs
		state['last_res'] = self.last_res
		return state

	def set_state(self, state):
		if not state:
			return
		for key, ctrl in self.inputs.items():
			if key in state:
				ctrl.SetValue(str(state[key]))
		if 'last_inputs' in state:
			self.last_inputs = state['last_inputs']
		if 'last_res' in state:
			self.last_res = state['last_res']

	def export_to_path(self, path):
		if self.last_inputs is None or self.last_res is None or not _REPORTLAB_AVAILABLE:
			return
		try:
			c = _pdf_canvas.Canvas(path, pagesize=_A4)
			W,H = _A4
			font='Helvetica'
			for f in ['C:/Windows/Fonts/msgothic.ttc', 'C:/Windows/Fonts/meiryo.ttc', 'C:/Windows/Fonts/yugothic.ttf', 'ipaexg.ttf','ipaexm.ttf','fonts/ipaexg.ttf','fonts/ipaexm.ttf']:
				if os.path.exists(f):
					try:
						_pdfmetrics.registerFont(_TTFont('JPStab',f)); font='JPStab'; break
					except Exception: pass
			left = 40; y = H - 40
			c.setFont(font,12)
			c.drawString(left, y, '最大安定傾斜角度計算書（セミ・トレーラ連結車）')
			y -= 24
			c.setFont(font,10)
			y -= 18
			for img_name in ['diagram.png', 'diafram.png']:
				if os.path.exists(img_name):
					try:
						img_w = 640; img_h = 200
						c.drawImage(img_name, left - 70, y - img_h, width=img_w, height=img_h, preserveAspectRatio=True, mask='auto')
						y -= img_h + 10
						break
					except Exception:
						pass
			if not img_name:
				y -= 10
			c.setFont(font,9)
			c.drawText(c.beginText(left, y))
			W1 = self.last_inputs['W1']; W1f = self.last_inputs['W1f']; W1r = self.last_inputs['W1r']
			T1f = self.last_inputs['T1f']; T1r = self.last_inputs['T1r']; H1 = self.last_inputs['H1']
			W2 = self.last_inputs['W2']; W2f = self.last_inputs['W2f']; W2r = self.last_inputs['W2r']
			T2f = self.last_inputs['T2f']; T2r = self.last_inputs['T2r']; H2 = self.last_inputs['H2']
			def draw_side_by_side_tables(x_start, y_start, left_data, right_data, left_title, right_title):
				table_w = 250; table_h = 18; title_h = 18
				x_l = x_start
				c.rect(x_l, y_start - title_h - table_h * len(left_data), table_w, title_h + table_h * len(left_data))
				c.setFont(font, 9)
				c.drawString(x_l + 4, y_start - 12, left_title)
				c.line(x_l, y_start - title_h, x_l + table_w, y_start - title_h)
				c.line(x_l + 130, y_start - title_h, x_l + 130, y_start - title_h - table_h * len(left_data))
				c.line(x_l + 200, y_start - title_h, x_l + 200, y_start - title_h - table_h * len(left_data))
				for i in range(1, len(left_data)):
					c.line(x_l, y_start - title_h - table_h * i, x_l + table_w, y_start - title_h - table_h * i)
				c.setFont(font, 8)
				for i, (label, val, unit) in enumerate(left_data):
					cy = y_start - title_h - table_h * (i + 1) + 6
					c.drawString(x_l + 4, cy, label)
					c.drawRightString(x_l + 195, cy, val)
					c.drawString(x_l + 205, cy, unit)
				x_r = x_start + table_w + 10
				c.rect(x_r, y_start - title_h - table_h * len(right_data), table_w, title_h + table_h * len(right_data))
				c.setFont(font, 9)
				c.drawString(x_r + 4, y_start - 12, right_title)
				c.line(x_r, y_start - title_h, x_r + table_w, y_start - title_h)
				c.line(x_r + 130, y_start - title_h, x_r + 130, y_start - title_h - table_h * len(right_data))
				c.line(x_r + 200, y_start - title_h, x_r + 200, y_start - title_h - table_h * len(right_data))
				for i in range(1, len(right_data)):
					c.line(x_r, y_start - title_h - table_h * i, x_r + table_w, y_start - title_h - table_h * i)
				c.setFont(font, 8)
				for i, (label, val, unit) in enumerate(right_data):
					cy = y_start - title_h - table_h * (i + 1) + 6
					c.drawString(x_r + 4, cy, label)
					c.drawRightString(x_r + 195, cy, val)
					c.drawString(x_r + 205, cy, unit)
				return y_start - title_h - table_h * max(len(left_data), len(right_data)) - 12
			left_simple = [
				(f'車両重量  W₁', f"{W1:.1f}", 'kg'),
				(f'前軸重量  W₁f', f"{W1f:.1f}", 'kg'),
				(f'後軸重量  W₁r', f"{W1r:.1f}", 'kg'),
				(f'前輪輪距  T₁f', f"{T1f:.3f}", 'm'),
				(f'後輪輪距(最外側) T₁r', f"{T1r:.3f}", 'm'),
				(f'重心高  H₁', f"{H1:.3f}", 'm'),
			]
			right_simple = [
				(f'車両重量  W₂', f"{W2:.1f}", 'kg'),
				(f'第5輪重量  W₂f', f"{W2f:.1f}", 'kg'),
				(f'後軸重量  W₂r', f"{W2r:.1f}", 'kg'),
				(f'ヒッチカプラー安定幅 T₂f = T₁r', f"{T2f:.3f}", 'm'),
				(f'後輪輪距(最外側) T₂r', f"{T2r:.3f}", 'm'),
				(f'重心高  H₂', f"{H2:.3f}", 'm'),
			]
			y = draw_side_by_side_tables(left, y, left_simple, right_simple, 'トラクタ諸元', 'トレーラ諸元')
			B1 = self.last_res.get('B1', 0)
			c.setFont(font, 9)
			c.drawString(left, y, f"②  トラクタ安定幅：B₁      (m)")
			y -= 16
			c.setFont(font, 8)
			c.drawString(left + 20, y, f"B₁ = (W₁f・T₁f + W₁r・T₁r) / (2・W₁) = ({W1f:.1f}×{T1f:.3f} + {W1r:.1f}×{T1r:.3f}) / (2×{W1:.1f}) = {B1:.4f}  m")
			y -= 18
			B2 = self.last_res.get('B2', 0)
			c.setFont(font, 9)
			c.drawString(left, y, f"③  トレーラ安定幅：B₂      (m)")
			y -= 16
			c.setFont(font, 8)
			c.drawString(left + 20, y, f"B₂ = (W₂f・T₂f + W₂r・T₂r) / (2・W₂) = ({W2f:.1f}×{T2f:.3f} + {W2r:.1f}×{T2r:.3f}) / (2×{W2:.1f}) = {B2:.4f}  m")
			y -= 18
			B = self.last_res.get('B', 0)
			c.setFont(font, 9)
			c.drawString(left, y, f"④  連結時安定幅：B         (m)")
			y -= 16
			c.setFont(font, 8)
			c.drawString(left + 20, y, f"B = (W₁・B₁ + W₂・B₂) / (W₁ + W₂) = ({W1:.1f}×{B1:.4f} + {W2:.1f}×{B2:.4f}) / ({W1:.1f}+{W2:.1f}) = {B:.4f}  m")
			y -= 18
			c.setFont(font, 10)
			c.drawString(left, y, '(2)  連結時の重心高：H      (m)')
			y -= 16
			Hc = self.last_res.get('H', 0)
			c.setFont(font, 8)
			c.drawString(left + 20, y, f"H = (H₁・W₁ + H₂・W₂) / (W₁ + W₂) = ({H1:.3f}×{W1:.1f} + {H2:.3f}×{W2:.1f}) / ({W1:.1f}+{W2:.1f}) = {Hc:.4f}  m")
			y -= 18
			theta = self.last_res.get('theta1', 0)
			c.setFont(font, 10)
			c.drawString(left, y, '(3)  連結時の最大安定傾斜角度：β')
			y -= 16
			c.setFont(font, 8)
			c.drawString(left + 20, y, f"tan θ₁ = B / H = {B:.4f} / {Hc:.4f} = {(B/Hc if Hc>0 else 0):.4f}")
			y -= 14
			c.drawString(left + 20, y, f"θ₁ = {theta:.2f}°≧35°")
			y -= 10
			c.showPage(); c.save()
		except Exception:
			pass


class ChassisFramePanel(wx.Panel):
	def __init__(self,parent):
		# 廃止: シャーシ強度計算パネルは未使用。型解析エラー抑止用に最低限属性定義。
		super().__init__(parent)
		self.last=None
		self.load_sizer = wx.FlexGridSizer(0,2,4,4)
		self.point_load_ctrls = []
		self.pos_ctrls = []
		self.load_count = wx.SpinCtrl(self, min=0, max=10, initial=0)

	def _row(self,sizer,label,default='',hint=''):
		h = wx.BoxSizer(wx.HORIZONTAL)
		h.Add(wx.StaticText(self,label=label),0,wx.RIGHT|wx.ALIGN_CENTER_VERTICAL,6)
		ctrl = wx.TextCtrl(self,value=default,size=wx.Size(90,-1),style=wx.TE_RIGHT)
		if hint:
			ctrl.SetHint(hint)
		h.Add(ctrl,0)
		sizer.Add(h,0,wx.EXPAND|wx.LEFT|wx.RIGHT|wx.TOP,4)
		return ctrl

	def _rebuild_loads(self,_=None):
		for c in self.load_sizer.GetChildren():
			item = c.GetWindow()
			if item: item.Destroy()
		self.point_load_ctrls.clear(); self.pos_ctrls.clear()
		count = self.load_count.GetValue()
		for i in range(count):
			self.load_sizer.Add(wx.StaticText(self,label=f'荷重{i+1}(kg)'),0,wx.ALIGN_CENTER_VERTICAL)
			pl = wx.TextCtrl(self,value='',size=wx.Size(70,-1),style=wx.TE_RIGHT)
			pl.SetHint('300')
			self.point_load_ctrls.append(pl); self.load_sizer.Add(pl,0)
			self.load_sizer.Add(wx.StaticText(self,label=f'位置{i+1}(mm)'),0,wx.ALIGN_CENTER_VERTICAL)
			pos = wx.TextCtrl(self,value='',size=wx.Size(70,-1),style=wx.TE_RIGHT)
			pos.SetHint(str(1000*(i+1)))
			self.pos_ctrls.append(pos); self.load_sizer.Add(pos,0)
		self.Layout()

	def on_calc(self,_): pass
	def on_export_pdf(self,_): pass


class TurningRadiusPanel(wx.Panel):
	def __init__(self,parent):
		super().__init__(parent)
		v=wx.BoxSizer(wx.VERTICAL)
		# 図表示: 最小回転半径レイアウト図 (存在すれば表示)
		img_candidates = ['turning_full.png','turning_semi.png','turning_radius.png','turning_diagram.png','turning.png','turning_layout.png']
		# 単一ファイル(二図並列)を優先: turning_diagram.png など
		side_by_side = ['turning_diagram.png','turning_radius.png','turning.png']
		bitmap_added = False
		bitmap_added = False
		for p in side_by_side:
			if os.path.exists(p):
				try:
					img = wx.Image(p, wx.BITMAP_TYPE_ANY)
					max_w = 880
					if img.GetWidth() > max_w:
						scale = max_w / img.GetWidth()
						img = img.Scale(max_w, int(img.GetHeight()*scale))
					bmp = wx.StaticBitmap(self, bitmap=wx.BitmapBundle.FromBitmap(wx.Bitmap(img)))
					v.Add(bmp,0,wx.ALIGN_CENTER|wx.ALL,6)
					bitmap_added = True
					break
				except Exception:
					pass
		# 個別ファイル2枚 (full/semi) があれば横並びで表示
		if not bitmap_added:
			pair = [p for p in ['turning_full.png','turning_semi.png'] if os.path.exists(p)]
			if pair:
				row = wx.BoxSizer(wx.HORIZONTAL)
				for pf in pair:
					try:
						img = wx.Image(pf, wx.BITMAP_TYPE_ANY)
						max_w_each = 420
						if img.GetWidth() > max_w_each:
							scale = max_w_each / img.GetWidth()
							img = img.Scale(max_w_each, int(img.GetHeight()*scale))
						bmp = wx.StaticBitmap(self, bitmap=wx.BitmapBundle.FromBitmap(wx.Bitmap(img)))
						row.Add(bmp,0,wx.ALL,4)
					except Exception:
						pass
				if row.GetChildren():
					v.Add(row,0,wx.ALIGN_CENTER|wx.TOP|wx.BOTTOM,4)
					bitmap_added = True
		if not bitmap_added:
			v.Add(wx.StaticText(self,label='(回転半径図ファイル未検出: turning_diagram.png)'),0,wx.ALIGN_CENTER|wx.ALL,4)
		# 入力を見本の書式に合わせて整理（(1)トラクタ諸元 / (2)トレーラ諸元）
		tractor_box = wx.StaticBox(self, label='(1) トラクタ諸元')
		tractor_s = wx.StaticBoxSizer(tractor_box, wx.VERTICAL)
		self.L1 = self._add(tractor_s, '軸距 L1 [m]', '', '3.450')
		self.i1_input = self._add(tractor_s, '前輪輪距の 1/2 値 I1 [m]', '', '1.030')
		# 派生値 I1 (Trf1/2) を表示用に追加（読み取り専用, m単位）
		row1 = wx.BoxSizer(wx.HORIZONTAL)
		row1.Add(wx.StaticText(self, label='前輪輪距の 1/2 値 I1 [m]'), 0, wx.RIGHT | wx.ALIGN_CENTER_VERTICAL, 6)
		self.i1_disp = wx.TextCtrl(self, value='', style=wx.TE_RIGHT | wx.TE_READONLY)
		self.i1_disp.SetHint('1.030')
		row1.Add(self.i1_disp, 0)
		tractor_s.Add(row1, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, 4)

		trailer_box = wx.StaticBox(self, label='(2) トレーラ諸元')
		trailer_s = wx.StaticBoxSizer(trailer_box, wx.VERTICAL)
		self.L2 = self._add(trailer_s, '軸距 L2 [m]', '', '8.870')
		self.i2_input = self._add(trailer_s, '後輪輪距の 1/2 値 I2 [m]', '', '0.930')
		# 派生値 I2 (Trf2/2) を表示用に追加（読み取り専用, m単位）
		row2 = wx.BoxSizer(wx.HORIZONTAL)
		row2.Add(wx.StaticText(self, label='後輪輪距の 1/2 値 I2 [m]'), 0, wx.RIGHT | wx.ALIGN_CENTER_VERTICAL, 6)
		self.i2_disp = wx.TextCtrl(self, value='', style=wx.TE_RIGHT | wx.TE_READONLY)
		self.i2_disp.SetHint('0.930')
		row2.Add(self.i2_disp, 0)
		trailer_s.Add(row2, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, 4)

		# 共通: カプラオフセット S と ハンドル切れ角 θ
		self.S = self._add(v, 'カプラオフセット S [m]', '', '0.650')
		# 文書書式ではθは使用しないため入力から除外
		# 補足ラベル
		v.Add(wx.StaticText(self, label='補足: I1=Trf1/2, I2=Trf2/2'), 0, wx.LEFT | wx.RIGHT | wx.TOP, 6)

		# グループをレイアウトへ追加
		v.Add(tractor_s, 0, wx.EXPAND | wx.ALL, 6)
		v.Add(trailer_s, 0, wx.EXPAND | wx.ALL, 6)

		# 入力変更時に派生値(I1/I2)を更新
		def _update_derived(_evt=None):
			try:
				i1_m = float(self.i1_input.GetValue())
				i2_m = float(self.i2_input.GetValue())
				self.i1_disp.SetValue(f"{i1_m:.3f}")
				self.i2_disp.SetValue(f"{i2_m:.3f}")
			except ValueError:
				self.i1_disp.SetValue('')
				self.i2_disp.SetValue('')
		self.i1_input.Bind(wx.EVT_TEXT, _update_derived)
		self.i2_input.Bind(wx.EVT_TEXT, _update_derived)
		_update_derived()
		btn_row=wx.BoxSizer(wx.HORIZONTAL)
		btn_calc=wx.Button(self,label='回転半径計算'); btn_calc.Bind(wx.EVT_BUTTON,self.on_calc); btn_row.Add(btn_calc,0,wx.RIGHT,8)
		btn_pdf=wx.Button(self,label='PDF出力'); btn_pdf.Bind(wx.EVT_BUTTON,self.on_export_pdf); btn_row.Add(btn_pdf,0)
		v.Add(btn_row,0,wx.ALIGN_CENTER|wx.ALL,6)
		# 結果TextCtrlは廃止（別ウィンドウのみ）
		self.last_values=None  # 計算結果保持 (Lc, R, 入力値)
		self.SetSizer(v)

	def _add(self,sizer,label,default='',hint=''):
		h=wx.BoxSizer(wx.HORIZONTAL)
		h.Add(wx.StaticText(self,label=label),0,wx.RIGHT|wx.ALIGN_CENTER_VERTICAL,6)
		t=wx.TextCtrl(self,value=default,style=wx.TE_RIGHT)
		if hint:
			t.SetHint(hint)
		h.Add(t,1)
		sizer.Add(h,0,wx.EXPAND|wx.LEFT|wx.RIGHT|wx.TOP,4)
		return t

	def on_calc(self,_):
		"""見本書式に合わせた最小回転半径計算。
		使用入力: L1, L2, I1, I2, S (すべて m)
		計算式:
		  LC = √(L2² + I2² − S²)
		  R  = √(L1² + (LC + I1)²)
		"""
		try:
			L1=float(self.L1.GetValue()); L2=float(self.L2.GetValue()); I1=float(self.i1_input.GetValue()); I2=float(self.i2_input.GetValue()); S=float(self.S.GetValue())
		except ValueError:
			wx.MessageBox('数値入力を確認してください。','入力エラー',wx.ICON_ERROR); return
		import math
		lc_sq = L2**2 + I2**2 - S**2
		if lc_sq < 0:
			wx.MessageBox('LC計算の平方根内が負です。Sが大き過ぎる可能性があります。','入力エラー',wx.ICON_ERROR); return
		LC = math.sqrt(lc_sq)
		R = math.sqrt(L1**2 + (LC + I1)**2)
		self.last_values = dict(L1=L1,L2=L2,I1=I1,I2=I2,S=S,LC=LC,R=R)
		text='\n'.join([
			'◆ 最小回転半径 計算結果 ◆',
			f"LC = {LC:.3f} m",
			f"R  = {R:.3f} m"
		])
		show_result('最小回転半径計算結果', text)

	def on_export_pdf(self,_):
		if self.last_values is None:
			wx.MessageBox('先に回転半径計算を実行してください。','PDF出力',wx.ICON_INFORMATION); return
		if not _REPORTLAB_AVAILABLE:
			wx.MessageBox('ReportLabが未インストールです。','PDF出力不可',wx.ICON_ERROR); return
		with wx.FileDialog(self,message='PDF保存',wildcard='PDF files (*.pdf)|*.pdf',style=wx.FD_SAVE|wx.FD_OVERWRITE_PROMPT,defaultFile='最小回転半径計算書.pdf') as dlg:
			if dlg.ShowModal()!=wx.ID_OK: return
			path=dlg.GetPath()
		vals=self.last_values
		try:
			# 見本書式: 図→(1)トラクタ諸元(m)→(2)トレーラ諸元(m)→(3)式展開
			c=_pdf_canvas.Canvas(path,pagesize=_A4)
			W,H=_A4
			font='Helvetica'
			for f in ['C:/Windows/Fonts/msgothic.ttc', 'C:/Windows/Fonts/meiryo.ttc', 'C:/Windows/Fonts/yugothic.ttf', 'ipaexg.ttf','ipaexm.ttf','fonts/ipaexg.ttf','fonts/ipaexm.ttf']:
				if os.path.exists(f):
					try:
						_pdfmetrics.registerFont(_TTFont('JPFontTR',f)); font='JPFontTR'; break
					except Exception: pass
			# 画像: 添付見本に合わせて turning.png を優先表示
			top_y=H-70
			pf=None
			if os.path.exists('turning.png'):
				pf='turning.png'
			else:
				alts=['turning_diagram.png','turning_radius.png','turning_full.png','turning_semi.png']
				for p in alts:
					if os.path.exists(p):
						pf=p; break
			if pf:
				try:
					img=wx.Image(pf,wx.BITMAP_TYPE_ANY)
					max_w=520; max_h=220
					sc=min(max_w/img.GetWidth(), max_h/img.GetHeight())
					new_w=int(img.GetWidth()*sc); new_h=int(img.GetHeight()*sc)
					# 図をさらに右へ配置
					c.drawImage(pf,120,top_y-new_h+10,width=new_w,height=new_h,preserveAspectRatio=True,mask='auto')
					top_y=top_y-new_h-6
				except Exception: pass
			# タイトル（左）/ ページ下部の中央ページ番号は省略
			c.setFont(font,14); c.drawString(40,H-50,'連結自動車の最小回転半径計算書')
			# 値は m 表示に統一（見本準拠）
			L1=vals['L1']; L2=vals['L2']; I1=vals['I1']; I2=vals['I2']; S=vals['S']; LC=vals['LC']; R=vals['R']
			# 諸元表関数（3列: 項目/値/単位）
			c.setFont(font,10)
			def table(x,y,title,rows,colw):
				row_h=18
				# ヘッダー行は設けず、行数分の枠に調整（例: 4行/2行）
				height=row_h*len(rows)
				width=sum(colw)
				# タイトルは枠の外上部に配置して重なり防止
				c.setFont(font,11); c.drawString(x+6,y+12,title); c.setFont(font,10)
				# 外枠は太線で描画
				c.setLineWidth(1.5)
				c.rect(x,y-height,width,height)
				# 各行の水平線（内部仕切り）を追加（行数に応じた枠）
				c.setLineWidth(0.8)
				for i in range(1, len(rows)):
					c.line(x, y - row_h*i, x + width, y - row_h*i)
				cx=x
				# 縦線（列区切り）。外枠に合わせるため線幅は内線と同じに。
				for wcol in colw[:-1]: cx+=wcol; c.line(cx,y,cx,y-height)
				for i,r in enumerate(rows):
					cy=y-row_h*(i+1)+5; cx=x+6
					for j,cell in enumerate(r): c.drawString(cx,cy,str(cell)); cx+=colw[j]
				# 下の余白は最小限
				return y-height-6
			# 列幅（合計幅を用紙右マージン内に収める）
			colw=[120,90,50]
			# 図との間隔を広げるため、諸元表の開始位置を下げる
			top_y=min(top_y, H-300) - 12
			# 左表は左マージン 40pt に配置
			left_x=40
			left_bottom=table(left_x,top_y,'(1) トラクタ諸元',[
				['最小回転半径 R', f"{R:.3f}", 'm'],
				['軸距 L1', f"{L1:.3f}", 'm'],
				['前輪輪距の 1/2 値 I1', f"{I1:.3f}", 'm'],
				['カプラオフセット S', f"{S:.3f}", 'm'],
			], colw)
			# 右表は用紙幅から右マージン40ptと表幅を差し引いた位置に配置（はみ出し防止）
			width=sum(colw)
			right_x = W - 40 - width
			# 左右の表が近すぎる場合は少し余白を追加
			if right_x - (left_x + width) < 20:
				right_x = left_x + width + 20
			right_bottom=table(right_x,top_y,'(2) トレーラ諸元',[
				['軸距 L2', f"{L2:.3f}", 'm'],
				['後輪輪距の 1/2 値 I2', f"{I2:.3f}", 'm'],
			], colw)
			# 式展開（さらに下げて図・諸元との余白を確保）
			y=min(left_bottom,right_bottom)-30
			# 下端マージンを確保（はみ出し防止）
			if y < 140:
				y = 140
			c.setFont(font,11); c.drawString(40,y,'(3) 連結時最小回転半径 R (m)')
			c.setFont(font,10); y-=18
			# LC の式（見本準拠: LC = √(L2^2 + I2^2 - S^2)）
			c.drawString(50,y,'LC = √( L2² + I2² - S² )'); y-=18
			c.drawString(50,y,f"LC = √( {L2:.3f}² + {I2:.3f}² - {S:.3f}² ) = {LC:.3f}"); y-=22
			# Li と DL の注記（見本の 0.3m を注記として表示）
			c.drawString(50,y,'Li = L2 + DL'); c.drawString(180,y,'DL = 0.3m'); y-=18
			c.drawString(50,y,f"Li = {L2:.3f} + 0.300 = {(L2+0.300):.3f}"); y-=22
			# R の式
			c.drawString(50,y,'R = √( L1² + (Lc + I1)² )'); y-=18
			c.drawString(50,y,f"R = √( {L1:.3f}² + ({LC:.3f} + {I1:.3f})² ) = {R:.3f}"); y-=20
			# 結果（見本の ≤ 判定行は省略）
			c.setFont(font,11); c.drawString(40,y,f"R = {R:.3f} m")
			c.showPage(); c.save(); _open_saved_pdf(path); wx.MessageBox('PDFを保存しました。','完了',wx.ICON_INFORMATION)
		except Exception as e:
			wx.MessageBox(f'PDF出力中エラー: {e}','エラー',wx.ICON_ERROR)

	def get_state(self):
		return {
			'L1': self.L1.GetValue(),
			'L2': self.L2.GetValue(),
			'i1_input': self.i1_input.GetValue(),
			'i2_input': self.i2_input.GetValue(),
			'S': self.S.GetValue(),
			'last_values': self.last_values
		}

	def set_state(self, state):
		if not state:
			return
		if 'L1' in state:
			self.L1.SetValue(str(state['L1']))
		if 'L2' in state:
			self.L2.SetValue(str(state['L2']))
		if 'i1_input' in state:
			self.i1_input.SetValue(str(state['i1_input']))
		if 'i2_input' in state:
			self.i2_input.SetValue(str(state['i2_input']))
		if 'S' in state:
			self.S.SetValue(str(state['S']))
		if 'last_values' in state:
			self.last_values = state['last_values']

	def export_to_path(self, path):
		if self.last_values is None or not _REPORTLAB_AVAILABLE:
			return
		vals=self.last_values
		try:
			c=_pdf_canvas.Canvas(path,pagesize=_A4)
			W,H=_A4
			font='Helvetica'
			for f in ['C:/Windows/Fonts/msgothic.ttc', 'C:/Windows/Fonts/meiryo.ttc', 'C:/Windows/Fonts/yugothic.ttf', 'ipaexg.ttf','ipaexm.ttf','fonts/ipaexg.ttf','fonts/ipaexm.ttf']:
				if os.path.exists(f):
					try:
						_pdfmetrics.registerFont(_TTFont('JPFontTR',f)); font='JPFontTR'; break
					except Exception: pass
			top_y=H-70
			pf=None
			if os.path.exists('turning.png'):
				pf='turning.png'
			else:
				alts=['turning_diagram.png','turning_radius.png','turning_full.png','turning_semi.png']
				for p in alts:
					if os.path.exists(p):
						pf=p; break
			if pf:
				try:
					img=wx.Image(pf,wx.BITMAP_TYPE_ANY)
					max_w=520; max_h=220
					sc=min(max_w/img.GetWidth(), max_h/img.GetHeight())
					new_w=int(img.GetWidth()*sc); new_h=int(img.GetHeight()*sc)
					c.drawImage(pf,120,top_y-new_h+10,width=new_w,height=new_h,preserveAspectRatio=True,mask='auto')
					top_y=top_y-new_h-6
				except Exception: pass
			c.setFont(font,14); c.drawString(40,H-50,'連結自動車の最小回転半径計算書')
			L1=vals['L1']; L2=vals['L2']; I1=vals['I1']; I2=vals['I2']; S=vals['S']; LC=vals['LC']; R=vals['R']
			c.setFont(font,10)
			def table(x,y,title,rows,colw):
				row_h=18
				height=row_h*len(rows)
				width=sum(colw)
				c.setFont(font,11); c.drawString(x+6,y+12,title); c.setFont(font,10)
				c.setLineWidth(1.5)
				c.rect(x,y-height,width,height)
				c.setLineWidth(0.8)
				for i in range(1, len(rows)):
					c.line(x, y - row_h*i, x + width, y - row_h*i)
				cx=x
				for wcol in colw[:-1]: cx+=wcol; c.line(cx,y,cx,y-height)
				for i,r in enumerate(rows):
					cy=y-row_h*(i+1)+5; cx=x+6
					for j,cell in enumerate(r): c.drawString(cx,cy,str(cell)); cx+=colw[j]
				return y-height-6
			colw=[120,90,50]
			top_y=min(top_y, H-300) - 12
			left_x=40
			left_bottom=table(left_x,top_y,'(1) トラクタ諸元',[
				['最小回転半径 R', f"{R:.3f}", 'm'],
				['軸距 L1', f"{L1:.3f}", 'm'],
				['前輪輪距の 1/2 値 I1', f"{I1:.3f}", 'm'],
				['カプラオフセット S', f"{S:.3f}", 'm'],
			], colw)
			width=sum(colw)
			right_x = W - 40 - width
			if right_x - (left_x + width) < 20:
				right_x = left_x + width + 20
			right_bottom=table(right_x,top_y,'(2) トレーラ諸元',[
				['軸距 L2', f"{L2:.3f}", 'm'],
				['後輪輪距の 1/2 値 I2', f"{I2:.3f}", 'm'],
			], colw)
			y=min(left_bottom,right_bottom)-30
			if y < 140:
				y = 140
			c.setFont(font,11); c.drawString(40,y,'(3) 連結時最小回転半径 R (m)')
			c.setFont(font,10); y-=18
			c.drawString(50,y,'LC = √( L2² + I2² - S² )'); y-=18
			c.drawString(50,y,f"LC = √( {L2:.3f}² + {I2:.3f}² - {S:.3f}² ) = {LC:.3f}"); y-=22
			c.drawString(50,y,'Li = L2 + DL'); c.drawString(180,y,'DL = 0.3m'); y-=18
			c.drawString(50,y,f"Li = {L2:.3f} + 0.300 = {(L2+0.300):.3f}"); y-=22
			c.drawString(50,y,'R = √( L1² + (Lc + I1)² )'); y-=18
			c.drawString(50,y,f"R = √( {L1:.3f}² + ({LC:.3f} + {I1:.3f})² ) = {R:.3f}"); y-=20
			c.setFont(font,11); c.drawString(40,y,f"R = {R:.3f} m")
			c.showPage(); c.save()
		except Exception:
			pass


class SafetyChainPanel(wx.Panel):
	"""安全チェーン強度計算書"""
	def __init__(self,parent):
		super().__init__(parent)
		root = wx.BoxSizer(wx.HORIZONTAL)
		# 図の読み込み（既定パスを順に探索）
		# StaticBitmap は生 Bitmap を設定（互換性重視）
		self.img = wx.StaticBitmap(self, bitmap=wx.BitmapBundle.FromBitmap(wx.Bitmap(220,220)))
		self._chain_path = self._find_chain_image()
		if self._chain_path and os.path.exists(self._chain_path):
			try:
				bmp = wx.Bitmap(self._chain_path, wx.BITMAP_TYPE_ANY)
				self.img.SetBitmap(wx.BitmapBundle.FromBitmap(bmp))
			except Exception as e:
				wx.MessageBox(f'画像読込エラー: {e}','エラー',wx.ICON_ERROR)
		else:
			wx.MessageBox('チェーン画像が見つかりませんでした。画像選択で指定してください。','案内',wx.ICON_INFORMATION)
		root.Add(self.img, 0, wx.ALL, 10)
		fg = wx.FlexGridSizer(0,3,6,8)
		self.inputs = {}
		def add_row(label, key, default='', hint=''):
			fg.Add(wx.StaticText(self,label=label))
			ctrl = wx.TextCtrl(self,value=str(default),style=wx.TE_RIGHT)
			if hint:
				ctrl.SetHint(hint)
			self.inputs[key]=ctrl
			fg.Add(ctrl,0,wx.EXPAND)
			fg.Add(wx.StaticText(self,label=''))
		# 材質名（自由入力）
		fg.Add(wx.StaticText(self,label='材質 名称'))
		self.material = wx.TextCtrl(self,value='')
		self.material.SetHint('SUS304')
		fg.Add(self.material,0,wx.EXPAND)
		fg.Add(wx.StaticText(self,label=''))
		add_row('チェーン1リンクの長さ L (mm)','L','','120')
		add_row('チェーン1リンクの幅 b (mm)','b','','60')
		add_row('チェーン素材の線径 d (mm)','d','','10')
		add_row('被牽引自動車の車両総重量 (kg) W','W','','1500')
		add_row('材質 引張強度 ob (kg/mm²)','ob','','40')
		btn_calc = wx.Button(self,label='計算')
		btn_pdf  = wx.Button(self,label='PDF出力')
		btn_img  = wx.Button(self,label='画像選択')
		btn_gen  = wx.Button(self,label='図生成')
		fg.Add(btn_calc); fg.Add(btn_pdf); fg.Add(btn_img); fg.Add(btn_gen); fg.AddGrowableCol(1,1)
		root.Add(fg, 1, wx.ALL|wx.EXPAND, 10)
		self.SetSizer(root)
		btn_calc.Bind(wx.EVT_BUTTON, self.on_calc)
		btn_pdf.Bind(wx.EVT_BUTTON, self.on_export_pdf)
		btn_img.Bind(wx.EVT_BUTTON, self.on_select_image)
		btn_gen.Bind(wx.EVT_BUTTON, self.on_generate_chain_image)
		self.last=None
	def on_generate_chain_image(self,_):
		try:
			from PIL import Image, ImageDraw
		except Exception:
			wx.MessageBox('Pillow が未インストールです。requirements.txt に pillow を追加してください。','エラー',wx.ICON_ERROR)
			return
		# 画像サイズと配色
		W,H = 360, 360
		bg = (255,255,255)
		line = (0,0,0)
		accent = (160,160,160)
		img = Image.new('RGB',(W,H),bg)
		draw = ImageDraw.Draw(img)
		# チェーンリンクのパラメータ（単一リンクを太めに描画）
		links = 1
		link_w = 160
		link_h = 80
		gap = 22
		x0 = 40
		y0 = H//2 - link_h//2
		stroke = 12
		for i in range(links):
			x = x0 + i*(link_w - gap)
			# 外周楕円（グレー塗り + 黒縁）
			draw.rounded_rectangle([x,y0,x+link_w,y0+link_h], radius=link_h//2, outline=line, fill=(180,180,180), width=2)
			# 内側（中空に見せるため白で塗る）
			inset = 18
			draw.rounded_rectangle([x+inset,y0+inset,x+link_w-inset,y0+link_h-inset], radius=(link_h//2-inset), outline=line, fill=bg, width=2)
		# フック図は不要（単一リンクのみ表示）

		# 寸法注記（添付見本に準拠: L, b, d）
		# L: 縦寸法（リンク外形の上下矢印 + 右側太め補助線 + ラベル枠）
		L_x = x0 + link_w//2
		L_top = y0 - 34
		L_bot = y0 + link_h + 34
		# 矢印線
		draw.line([(L_x, L_top), (L_x, y0)], fill=line, width=3)
		draw.polygon([(L_x-7, L_top+12), (L_x+7, L_top+12), (L_x, L_top)], fill=line)
		draw.line([(L_x, y0+link_h), (L_x, L_bot)], fill=line, width=3)
		draw.polygon([(L_x-7, L_bot-12), (L_x+7, L_bot-12), (L_x, L_bot)], fill=line)
		# 補助寸法線（右側太め）
		draw.line([(L_x+30, y0-10), (L_x+30, y0+link_h+10)], fill=(0,0,0), width=2)
		# ラベル枠付きで強調
		label_w, label_h = 22, 18
		lx = L_x + 36; ly = (L_top+L_bot)//2 - label_h//2
		draw.rectangle([lx, ly, lx+label_w, ly+label_h], outline=line, fill=(255,255,255))
		draw.text((lx+6, ly+2), 'L', fill=line)

		# b: 横寸法（リンク外形の左右矢印 + 下側太め補助線 + ラベル枠）
		b_y = y0 + link_h//2
		b_left = x0 - 34
		b_right = x0 + link_w + 34
		# 左右矢印
		draw.line([(b_left, b_y), (x0, b_y)], fill=line, width=3)
		draw.polygon([(b_left+14, b_y-6), (b_left+14, b_y+6), (b_left, b_y)], fill=line)
		draw.line([(x0+link_w, b_y), (b_right, b_y)], fill=line, width=3)
		draw.polygon([(b_right-14, b_y-6), (b_right-14, b_y+6), (b_right, b_y)], fill=line)
		# 補助寸法線（下側太め）
		draw.line([(x0-8, b_y+30), (x0+link_w+8, b_y+30)], fill=(0,0,0), width=2)
		# ラベル枠付きで強調
		bx = (b_left+b_right)//2 - 14; by = b_y - 26
		draw.rectangle([bx, by, bx+24, by+18], outline=line, fill=(255,255,255))
		draw.text((bx+6, by+2), 'b', fill=line)

		# d: 線径（左側に短い矢印で厚みを示す）
		d_mid_y = y0 + link_h//2
		d_base_x = x0 + inset//2
		d_len = 28
		draw.line([(d_base_x - d_len, d_mid_y), (d_base_x, d_mid_y)], fill=line, width=2)
		draw.polygon([(d_base_x - d_len + 12, d_mid_y-6), (d_base_x - d_len + 12, d_mid_y+6), (d_base_x - d_len, d_mid_y)], fill=line)
		draw.text((d_base_x - d_len - 14, d_mid_y - 22), 'd', fill=line)
		# 保存先
		out_path = os.path.join(os.getcwd(),'chain.png')
		img.save(out_path, format='PNG')
		self._chain_path = out_path
		try:
			bmp = wx.Bitmap(self._chain_path, wx.BITMAP_TYPE_ANY)
			self.img.SetBitmap(wx.BitmapBundle.FromBitmap(bmp))
			self.Layout()
		except Exception:
			pass
		wx.MessageBox(f'チェーン図を生成し保存しました:\n{out_path}','完了',wx.ICON_INFORMATION)

	def _find_chain_image(self):
		candidates = [
			'chain.png',
			os.path.join('export','trailer_app','lib','chain.png'),
			os.path.join('lib','chain.png'),
			os.path.join('scripts','chain.png'),
		]
		for p in candidates:
			if os.path.exists(p):
				return p
		return None

	def on_select_image(self,_):
		with wx.FileDialog(self,message='チェーン画像を選択',wildcard='Image files (*.png;*.jpg;*.jpeg)|*.png;*.jpg;*.jpeg',style=wx.FD_OPEN|wx.FD_FILE_MUST_EXIST) as dlg:
			if dlg.ShowModal()!=wx.ID_OK:
				return
			self._chain_path = dlg.GetPath()
			try:
				bmp = wx.Bitmap(self._chain_path, wx.BITMAP_TYPE_ANY)
				self.img.SetBitmap(wx.BitmapBundle.FromBitmap(bmp))
				self.Layout()
			except Exception as e:
				wx.MessageBox(f'画像読み込みエラー: {e}','エラー',wx.ICON_ERROR)

	def _vals(self):
		def f(ctrl):
			try:
				return float(ctrl.GetValue())
			except Exception:
				return 0.0
		return {k: f(v) for k,v in self.inputs.items()}

	def on_calc(self,_):
		v = self._vals()
		import math
		A = math.pi*(v['d']/2.0)**2
		W_per = v['W']/2.0
		omax = v['W']/A if A>0 else 0.0
		omax2 = W_per/A if A>0 else 0.0
		fb = (v['ob']/omax2) if omax2>0 else 0.0
		# 2倍荷重に対する判定（総荷重 2W → 1本当たり W → 応力 W/A = omax）
		fb2 = (v['ob']/omax) if omax>0 else 0.0
		judge = '適合 (2Wに耐える)' if fb2 >= 1.0 else '不適合 (不足)'
		self.last = dict(A=A, omax=omax, omax2=omax2, fb=fb, fb2=fb2, judge=judge, material=self.material.GetValue(), **v)
		wx.MessageBox(
			f"材質: {self.material.GetValue()}\nA={A:.2f} mm^2\nσ(総)={omax:.3f} kg/mm2\nσ(1本)={omax2:.3f} kg/mm2\n安全率(通常) fb={fb:.2f}\n安全率(2W) fb2={fb2:.2f}\n判定: {judge}",
			'計算結果', wx.ICON_INFORMATION)

	def on_export_pdf(self,_):
		if self.last is None:
			wx.MessageBox('先に計算を実行してください。','PDF出力',wx.ICON_INFORMATION); return
		if not _REPORTLAB_AVAILABLE:
			wx.MessageBox('ReportLabが未インストールです。','PDF出力不可',wx.ICON_ERROR); return
		with wx.FileDialog(self,message='PDF保存',wildcard='PDF files (*.pdf)|*.pdf',style=wx.FD_SAVE|wx.FD_OVERWRITE_PROMPT,defaultFile='安全チェーン強度計算書.pdf') as dlg:
			if dlg.ShowModal()!=wx.ID_OK: return
			path = dlg.GetPath()
			try:
				c = _pdf_canvas.Canvas(path, pagesize=_A4)
				W,H = _A4
				font='Helvetica'
				for f in ['C:/Windows/Fonts/msgothic.ttc', 'C:/Windows/Fonts/meiryo.ttc', 'C:/Windows/Fonts/yugothic.ttf', 'ipaexg.ttf','ipaexm.ttf','fonts/ipaexg.ttf','fonts/ipaexm.ttf']:
					if os.path.exists(f):
						try:
							_pdfmetrics.registerFont(_TTFont('JPChain',f)); font='JPChain'; break
						except Exception: pass
				left=40; y=H-40
				c.setFont(font,14); c.drawString(left,y,'安全チェーン強度計算書'); y-=24; c.setFont(font,9)
				# 図（中央寄せで拡大）
				img_path = None
				if self._chain_path and os.path.exists(self._chain_path):
					img_path = self._chain_path
				elif os.path.exists('chain.png'):
					img_path = 'chain.png'
				if img_path:
					try:
						img_w=360; img_h=200
						x = (W - img_w) / 2
						c.drawImage(img_path, x, y-img_h, width=img_w, height=img_h, preserveAspectRatio=True, mask='auto')
						y -= img_h + 10
					except Exception:
						pass
				v = self.last
				def table(x,y,cw,rh,rows):
					c.rect(x,y-rh*len(rows),sum(cw),rh*len(rows))
					cx=x
					for w in cw:
						c.line(cx,y,cx,y-rh*len(rows)); cx+=w
					c.line(cx,y,cx,y-rh*len(rows))
					for i in range(1,len(rows)):
						c.line(x,y-rh*i,x+sum(cw),y-rh*i)
					for r_i,row in enumerate(rows):
						tx=x+4; ty=y-rh*r_i-12
						for j,cell in enumerate(row):
							c.drawString(tx,ty,str(cell)); tx+=cw[j]
					return y-rh*len(rows)-10
				y=table(left,y,[180,120,120],18,[
					['項目','値','単位'],
					['材質 名称', str(v.get('material','')), ''],
					['チェーン1リンクの長さ L', f"{v.get('L',0.0):.1f}", 'mm'],
					['チェーン1リンクの幅 b', f"{v.get('b',0.0):.1f}", 'mm'],
					['チェーン素材の線径 d', f"{v.get('d',0.0):.1f}", 'mm'],
					['被牽引自動車の車両総重量 W', f"{v.get('W',0.0):.1f}", 'kg'],
					['材質 引張強度 ob', f"{v.get('ob',0.0):.2f}", 'kg/mm2'],
				])
				y=table(left,y,[180,120,120],18,[
					['計算結果','値','単位'],
					['断面積 A = π(d/2)^2', f"{v.get('A',0.0):.2f}", 'mm2'],
					['引張応力(総) omax = W/A', f"{v.get('omax',0.0):.3f}", 'kg/mm2'],
					['1本当たり omax2 = (W/2)/A', f"{v.get('omax2',0.0):.3f}", 'kg/mm2'],
					['安全率 fb = ob/omax2', f"{v.get('fb',0.0):.2f}", ''],
					['安全率(2W) fb2 = ob/omax', f"{v.get('fb2',0.0):.2f}", ''],
					['判定 (2W耐力)', str(v.get('judge','')), ''],
				])
				c.setFont(font,10); c.drawString(left,y,'計算式'); c.setFont(font,8); y-=18
				c.drawString(left,y,'A = π(d/2)^2'); y-=12
				c.drawString(left,y,'omax = W / A,  omax2 = (W/2) / A'); y-=12
				c.drawString(left,y,'fb = ob / omax2'); y-=12
				# 根拠・考え方
				y -= 6
				c.setFont(font,10); c.drawString(left, y, '根拠・考え方'); y -= 14; c.setFont(font,8)
				c.drawString(left+5, y, '・チェーン1本に作用する荷重は連結時の分配を想定（通常 W/2, 2W時は各W）。'); y -= 12
				c.drawString(left+5, y, '・応力は簡易的に重量(kg)を力とみなした kg/mm² 表記で評価し、安全側の目安。'); y -= 12
				c.drawString(left+5, y, '・材質の引張強度 ob と比較して安全率を算出し、2W耐力の適否を判断。'); y -= 12
				c.showPage(); c.save(); _open_saved_pdf(path); wx.MessageBox('PDFを保存しました。','完了',wx.ICON_INFORMATION)
			except Exception as e:
				wx.MessageBox(f'PDF出力中エラー: {e}','エラー',wx.ICON_ERROR)

	def get_state(self):
		state = {'material': self.material.GetValue(), 'inputs': {k: v.GetValue() for k, v in self.inputs.items()}, 'chain_path': self._chain_path, 'last': self.last}
		return state

	def set_state(self, state):
		if not state: return
		if 'material' in state: self.material.SetValue(str(state['material']))
		if 'inputs' in state:
			for k, v in state['inputs'].items():
				if k in self.inputs: self.inputs[k].SetValue(str(v))
		if 'chain_path' in state and state['chain_path']:
			self._chain_path = state['chain_path']
			if os.path.exists(self._chain_path):
				try:
					bmp = wx.Bitmap(self._chain_path, wx.BITMAP_TYPE_ANY); self.img.SetBitmap(wx.BitmapBundle.FromBitmap(bmp)); self.Layout()
				except Exception: pass
		if 'last' in state: self.last = state['last']

	def export_to_path(self, path):
		if self.last is None or not _REPORTLAB_AVAILABLE: return
		try:
			c = _pdf_canvas.Canvas(path, pagesize=_A4); W,H = _A4; font='Helvetica'
			for f in ['C:/Windows/Fonts/msgothic.ttc', 'C:/Windows/Fonts/meiryo.ttc', 'C:/Windows/Fonts/yugothic.ttf', 'ipaexg.ttf','ipaexm.ttf','fonts/ipaexg.ttf','fonts/ipaexm.ttf']:
				if os.path.exists(f):
					try: _pdfmetrics.registerFont(_TTFont('JPChain',f)); font='JPChain'; break
					except Exception: pass
			left=40; y=H-40; c.setFont(font,14); c.drawString(left,y,'安全チェーンの強度検討書'); y-=24; c.setFont(font,9)
			img_path = None
			if self._chain_path and os.path.exists(self._chain_path): img_path = self._chain_path
			elif os.path.exists('chain.png'): img_path = 'chain.png'
			if img_path:
				try: img_w=360; img_h=200; x = (W - img_w) / 2; c.drawImage(img_path, x, y-img_h, width=img_w, height=img_h, preserveAspectRatio=True, mask='auto'); y -= img_h + 10
				except Exception: pass
			v = self.last
			def table(x,y,cw,rh,rows):
				c.rect(x,y-rh*len(rows),sum(cw),rh*len(rows)); cx=x
				for w in cw: c.line(cx,y,cx,y-rh*len(rows)); cx+=w
				c.line(cx,y,cx,y-rh*len(rows))
				for i in range(1,len(rows)): c.line(x,y-rh*i,x+sum(cw),y-rh*i)
				for r_i,row in enumerate(rows):
					tx=x+4; ty=y-rh*r_i-12
					for j,cell in enumerate(row): c.drawString(tx,ty,str(cell)); tx+=cw[j]
				return y-rh*len(rows)-10
			y=table(left,y,[180,120,120],18,[['項目','値','単位'],['材質 名称', str(v.get('material','')), ''],['チェーン1リンクの長さ L', f"{v.get('L',0.0):.1f}", 'mm'],['チェーン1リンクの幅 b', f"{v.get('b',0.0):.1f}", 'mm'],['チェーン素材の線径 d', f"{v.get('d',0.0):.1f}", 'mm'],['被牽引自動車の車両総重量 W', f"{v.get('W',0.0):.1f}", 'kg'],['材質 引張強度 ob', f"{v.get('ob',0.0):.2f}", 'kg/mm2'],])
			y=table(left,y,[180,120,120],18,[['計算結果','値','単位'],['断面積 A = π(d/2)^2', f"{v.get('A',0.0):.2f}", 'mm2'],['引張応力(総) omax = W/A', f"{v.get('omax',0.0):.3f}", 'kg/mm2'],['1本当たり omax2 = (W/2)/A', f"{v.get('omax2',0.0):.3f}", 'kg/mm2'],['安全率 fb = ob/omax2', f"{v.get('fb',0.0):.2f}", ''],['安全率(2W) fb2 = ob/omax', f"{v.get('fb2',0.0):.2f}", ''],['判定 (2W耐力)', str(v.get('judge','')), ''],])
			c.setFont(font,10); c.drawString(left,y,'計算式'); c.setFont(font,8); y-=18
			c.drawString(left,y,'A = π(d/2)^2'); y-=12; c.drawString(left,y,'omax = W / A,  omax2 = (W/2) / A'); y-=12; c.drawString(left,y,'fb = ob / omax2'); y-=12
			# 根拠・考え方
			y -= 6
			c.setFont(font,10); c.drawString(left, y, '根拠・考え方'); y -= 14; c.setFont(font,8)
			c.drawString(left+5, y, '・荷重分配の仮定: 通常は2本で分担(W/2)、2W時は各W。'); y -= 12
			c.drawString(left+5, y, '・応力は kg/mm² の簡易表記で比較し、材質の引張強度 ob で安全率を評価。'); y -= 12
			c.drawString(left+5, y, '・図示寸法 L,b,d は形状理解の補助で、強度計算では d に基づく断面積 A を使用。'); y -= 12
			c.showPage(); c.save()
		except Exception: pass

class AxleStrengthPanel(wx.Panel):
	def __init__(self, parent):
		super().__init__(parent)
		v = wx.BoxSizer(wx.VERTICAL)
		# 図表示: 車軸寸法入力補助 (存在すれば表示)
		img_candidates = ['axle.png','axle_diagram.png','axle.jpg','axle_diagram.jpeg']
		bitmap_added = False
		for p in img_candidates:
			if os.path.exists(p):
				try:
					img = wx.Image(p, wx.BITMAP_TYPE_ANY)
					max_w = 820
					if img.GetWidth() > max_w:
						scale = max_w / img.GetWidth()
						img = img.Scale(max_w, int(img.GetHeight()*scale))
					bmp = wx.StaticBitmap(self, bitmap=wx.BitmapBundle.FromBitmap(wx.Bitmap(img)))
					v.Add(bmp, 0, wx.ALIGN_CENTER | wx.ALL, 6)
					bitmap_added = True
					break
				except Exception:
					continue
		if not bitmap_added:
			v.Add(wx.StaticText(self, label='(車軸図ファイル未検出: axle.png)'), 0, wx.ALIGN_CENTER | wx.ALL, 4)
		self.W = self._add(v, '車両総重量 W [kg]:', '', '4000')
		self.wheels = self._add(v, '車輪数 n:', '', '2')
		self.d = self._add(v, '車軸径 d [mm]:', '', '60')
		self.deltaS = self._add(v, '軸中心～軸受中心距離 ΔS [mm]:', '', '500')
		self.tensile = self._add(v, '引張強さ θb [kg/cm²]:', '', '55')
		self.yield_pt = self._add(v, '降伏点 θy [kg/cm²]:', '', '40')
		# 降伏点の説明ツールチップ追加
		self.yield_pt.SetToolTip('降伏点: 材料が弾性域を超えて塑性変形(永久変形)が始まる限界応力。設計ではこの値以下の許容応力を設定し永久変形を防止します。単位 kg/cm²')
		btn_row = wx.BoxSizer(wx.HORIZONTAL)
		btn_calc = wx.Button(self, label='車軸強度計算')
		btn_calc.Bind(wx.EVT_BUTTON, self.on_calc)
		btn_row.Add(btn_calc, 0, wx.RIGHT, 8)
		btn_pdf = wx.Button(self, label='PDF出力')
		btn_pdf.Bind(wx.EVT_BUTTON, self.on_export_pdf)
		btn_row.Add(btn_pdf, 0)
		v.Add(btn_row, 0, wx.ALIGN_CENTER | wx.ALL, 6)
		# 結果は別ウィンドウ表示のみ
		self.last = None
		self.SetSizer(v)

	def _add(self, sizer, label, default='', hint=''):
		h = wx.BoxSizer(wx.HORIZONTAL)
		h.Add(wx.StaticText(self, label=label), 0, wx.RIGHT | wx.ALIGN_CENTER_VERTICAL, 6)
		t = wx.TextCtrl(self, value=default, style=wx.TE_RIGHT)
		if hint:
			t.SetHint(hint)
		h.Add(t, 1)
		sizer.Add(h, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, 4)
		return t

	def on_calc(self, _):
		try:
			W = float(self.W.GetValue())
			d = float(self.d.GetValue())
			deltaS = float(self.deltaS.GetValue())
			tb = float(self.tensile.GetValue())
			ty = float(self.yield_pt.GetValue())
			wheels = int(self.wheels.GetValue())
		except ValueError:
			wx.MessageBox('数値入力を確認してください。', '入力エラー', wx.ICON_ERROR); return
		try:
			res = compute_axle_strength(W, d, deltaS, tb, ty, wheels)
		except ValueError as e:
			wx.MessageBox(str(e), '入力エラー', wx.ICON_ERROR); return
		self.last = dict(W=W, d=d, deltaS=deltaS, tb=tb, ty=ty, wheels=wheels, **res)
		text='\n'.join([
			'◆ 車軸強度計算結果 ◆',
			f"車輪数 n = {wheels}",
			f"1輪当たり荷重 P = {res['P']:.1f} kg (P = W / n)",
			f"断面係数 Z = {res['Z']:.2f} cm³",
			f"曲げモーメント M = {res['M']:.1f} kg·cm",
			f"曲げ応力 σb = {res['sigma_b']:.2f} kg/cm²",
			f"破断安全率 = {res['sf_break']:.2f} ({'適' if res['ok_break'] else '否'})",
			f"降伏安全率 = {res['sf_yield']:.2f} ({'適' if res['ok_yield'] else '否'})",
		])
		show_result('車軸強度計算結果', text)

	def on_export_pdf(self, _):
		if self.last is None:
			wx.MessageBox('先に計算を実行してください。', 'PDF出力', wx.ICON_INFORMATION); return
		if not _REPORTLAB_AVAILABLE:
			wx.MessageBox('ReportLabが未インストールです。', 'PDF出力不可', wx.ICON_ERROR); return
		with wx.FileDialog(self, message='PDF保存', wildcard='PDF files (*.pdf)|*.pdf', style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT, defaultFile='車軸強度計算書.pdf') as dlg:
			if dlg.ShowModal() != wx.ID_OK:
				return
			path = dlg.GetPath()
		try:
			c = _pdf_canvas.Canvas(path, pagesize=_A4)
			w, h = _A4
			font = 'Helvetica'
			for f in ['C:/Windows/Fonts/msgothic.ttc', 'C:/Windows/Fonts/meiryo.ttc', 'C:/Windows/Fonts/yugothic.ttf', 'ipaexg.ttf','ipaexm.ttf','fonts/ipaexg.ttf','fonts/ipaexm.ttf']:
				if os.path.exists(f):
					try:
						_pdfmetrics.registerFont(_TTFont('JPaxle', f)); font='JPaxle'; break
					except Exception:
						pass
			v = self.last
			c.setFont(font,14)
			c.drawString(40,h-50,'車軸強度計算書')
			c.setFont(font,9)
			start_y = h-90
			# 入力諸元表
			rows = [
				['項目','値','単位','項目','値','単位'],
				['車両総重量 W', f"{v['W']:.1f}", 'kg', '車輪数 n', f"{v['wheels']}", ''],
				['1輪荷重 P', f"{v['P']:.1f}", 'kg', '距離 ΔS', f"{v['deltaS']:.1f}", 'mm'],
				['軸径 d', f"{v['d']:.1f}", 'mm', '断面係数 Z', f"{v['Z']:.2f}", 'cm³'],
				['引張強さ θb', f"{v['tb']:.1f}", 'kg/cm²', '降伏点 θy', f"{v['ty']:.1f}", 'kg/cm²'],
			]
			col_w = [80,65,50,80,65,50]
			def table(x,y,cw,rh,data):
				width = sum(cw); height = rh*len(data)
				c.rect(x,y-height,width,height)
				for i in range(1,len(data)):
					c.line(x,y-rh*i,x+width,y-rh*i)
				# 縦線
				cx = x
				for idx,wcol in enumerate(cw[:-1]):
					cx += wcol
					c.line(cx, y, cx, y-height)
				for r,row in enumerate(data):
					for j,cell in enumerate(row):
						c.drawString(x+5+sum(cw[:j]), y-rh*(r+1)+4, cell)
				return y-height-20
			next_y = table(40,start_y,col_w,16,rows)
			# 結果式展開
			c.setFont(font,11)
			c.drawString(40,next_y,'(1) 1輪当たり荷重 P の計算')
			c.setFont(font,9)
			c.drawString(55,next_y-14,f"P = W / n = {v['W']:.1f} / {v['wheels']} = {v['P']:.1f} kg")
			c.setFont(font,11)
			z_y = next_y-40
			c.drawString(40,z_y,'(2) 断面係数 Z の計算')
			c.setFont(font,9)
			d_cm = v['d']/10.0
			c.drawString(55,z_y-14,f"Z = π × d³ / 32 = π × {d_cm:.2f}³ / 32 = {v['Z']:.2f} cm³")
			c.setFont(font,11)
			m_y = z_y-40
			c.drawString(40,m_y,'(2) 曲げモーメント M の計算')
			c.setFont(font,9)
			c.drawString(55,m_y-14,f"M = P × ΔS = {v['P']:.1f} × {v['deltaS']/10.0:.1f} = {v['M']:.1f} kg·cm")
			c.setFont(font,11)
			sig_y = m_y-40
			c.drawString(40,sig_y,'(3) 曲げ応力 σb の計算')
			c.setFont(font,9)
			c.drawString(55,sig_y-14,f"σb = M / Z = {v['M']:.1f} / {v['Z']:.2f} = {v['sigma_b']:.2f} kg/cm²")
			c.setFont(font,11)
			sf_y = sig_y-50
			c.drawString(40,sf_y,'(4) 安全率の計算 (荷重倍率2.5倍)')
			c.setFont(font,9)
			c.drawString(55,sf_y-14,f"破断安全率 = θb / (2.5 × σb) = {v['tb']:.1f} / (2.5×{v['sigma_b']:.2f}) = {v['sf_break']:.2f} {'>1.6 適合' if v['ok_break'] else '≦1.6 不適合'}")
			c.drawString(55,sf_y-28,f"降伏安全率 = θy / (2.5 × σb) = {v['ty']:.1f} / (2.5×{v['sigma_b']:.2f}) = {v['sf_yield']:.2f} {'>1.3 適合' if v['ok_yield'] else '≦1.3 不適合'}")
			final_y = sf_y-60
			c.setFont(font,12)
			c.drawString(40,final_y, f"総合判定: {'基準を満足する' if (v['ok_break'] and v['ok_yield']) else '基準を満足しない'}")
			# 根拠・考え方
			final_y -= 18
			c.setFont(font,11); c.drawString(40, final_y, '根拠・考え方'); final_y -= 14; c.setFont(font,9)
			c.drawString(45, final_y, '・丸棒の断面係数 Z = πd³/32 を用い、M/Z で曲げ応力を算出。'); final_y -= 12
			c.drawString(45, final_y, '・曲げモーメントは 1輪荷重 P と支点距離 ΔS の積で近似 (M=P×ΔS)。'); final_y -= 12
			c.drawString(45, final_y, '・材質の引張強さ θb および降伏点 θy と比較し、荷重倍率2.5を安全側の設計目安として採用。'); final_y -= 12
			c.drawString(45, final_y, '・単位換算: d,ΔS は cm 換算して計算、応力は kg/cm² 表記で整理。')
			c.showPage(); c.save(); wx.MessageBox('PDFを保存しました。','完了',wx.ICON_INFORMATION)
		except Exception as e:
			wx.MessageBox(f'PDF出力中エラー: {e}', 'エラー', wx.ICON_ERROR)

	def get_state(self):
		return {
			'W': self.W.GetValue(),
			'wheels': self.wheels.GetValue(),
			'd': self.d.GetValue(),
			'deltaS': self.deltaS.GetValue(),
			'tensile': self.tensile.GetValue(),
			'yield_pt': self.yield_pt.GetValue(),
			'last': self.last
		}

	def set_state(self, state):
		if not state:
			return
		if 'W' in state:
			self.W.SetValue(str(state['W']))
		if 'wheels' in state:
			self.wheels.SetValue(str(state['wheels']))
		if 'd' in state:
			self.d.SetValue(str(state['d']))
		if 'deltaS' in state:
			self.deltaS.SetValue(str(state['deltaS']))
		if 'tensile' in state:
			self.tensile.SetValue(str(state['tensile']))
		if 'yield_pt' in state:
			self.yield_pt.SetValue(str(state['yield_pt']))
		if 'last' in state:
			self.last = state['last']

	def export_to_path(self, path):
		if self.last is None or not _REPORTLAB_AVAILABLE:
			return
		try:
			c = _pdf_canvas.Canvas(path, pagesize=_A4)
			w, h = _A4
			font = 'Helvetica'
			for f in ['C:/Windows/Fonts/msgothic.ttc', 'C:/Windows/Fonts/meiryo.ttc', 'C:/Windows/Fonts/yugothic.ttf', 'ipaexg.ttf','ipaexm.ttf','fonts/ipaexg.ttf','fonts/ipaexm.ttf']:
				if os.path.exists(f):
					try:
						_pdfmetrics.registerFont(_TTFont('JPaxle', f)); font='JPaxle'; break
					except Exception:
						pass
			v = self.last
			c.setFont(font,14)
			c.drawString(40,h-50,'車軸強度計算書')
			c.setFont(font,9)
			start_y = h-90
			rows = [
				['項目','値','単位','項目','値','単位'],
				['車両総重量 W', f"{v['W']:.1f}", 'kg', '車輪数 n', f"{v['wheels']}", ''],
				['1輪荷重 P', f"{v['P']:.1f}", 'kg', '距離 ΔS', f"{v['deltaS']:.1f}", 'mm'],
				['軸径 d', f"{v['d']:.1f}", 'mm', '断面係数 Z', f"{v['Z']:.2f}", 'cm³'],
				['引張強さ θb', f"{v['tb']:.1f}", 'kg/cm²', '降伏点 θy', f"{v['ty']:.1f}", 'kg/cm²'],
			]
			col_w = [80,65,50,80,65,50]
			def table(x,y,cw,rh,data):
				width = sum(cw); height = rh*len(data)
				c.rect(x,y-height,width,height)
				for i in range(1,len(data)):
					c.line(x,y-rh*i,x+width,y-rh*i)
				cx = x
				for idx,wcol in enumerate(cw[:-1]):
					cx += wcol
					c.line(cx, y, cx, y-height)
				for r,row in enumerate(data):
					for j,cell in enumerate(row):
						c.drawString(x+5+sum(cw[:j]), y-rh*(r+1)+4, cell)
				return y-height-20
			next_y = table(40,start_y,col_w,16,rows)
			c.setFont(font,11)
			c.drawString(40,next_y,'(1) 1輪当たり荷重 P の計算')
			c.setFont(font,9)
			c.drawString(55,next_y-14,f"P = W / n = {v['W']:.1f} / {v['wheels']} = {v['P']:.1f} kg")
			c.setFont(font,11)
			z_y = next_y-40
			c.drawString(40,z_y,'(2) 断面係数 Z の計算')
			c.setFont(font,9)
			d_cm = v['d']/10.0
			c.drawString(55,z_y-14,f"Z = π × d³ / 32 = π × {d_cm:.2f}³ / 32 = {v['Z']:.2f} cm³")
			c.setFont(font,11)
			m_y = z_y-40
			c.drawString(40,m_y,'(2) 曲げモーメント M の計算')
			c.setFont(font,9)
			c.drawString(55,m_y-14,f"M = P × ΔS = {v['P']:.1f} × {v['deltaS']/10.0:.1f} = {v['M']:.1f} kg·cm")
			c.setFont(font,11)
			sig_y = m_y-40
			c.drawString(40,sig_y,'(3) 曲げ応力 σb の計算')
			c.setFont(font,9)
			c.drawString(55,sig_y-14,f"σb = M / Z = {v['M']:.1f} / {v['Z']:.2f} = {v['sigma_b']:.2f} kg/cm²")
			c.setFont(font,11)
			sf_y = sig_y-50
			c.drawString(40,sf_y,'(4) 安全率の計算 (荷重倍率2.5倍)')
			c.setFont(font,9)
			c.drawString(55,sf_y-14,f"破断安全率 = θb / (2.5 × σb) = {v['tb']:.1f} / (2.5×{v['sigma_b']:.2f}) = {v['sf_break']:.2f} {'>1.6 適合' if v['ok_break'] else '≦1.6 不適合'}")
			c.drawString(55,sf_y-28,f"降伏安全率 = θy / (2.5 × σb) = {v['ty']:.1f} / (2.5×{v['sigma_b']:.2f}) = {v['sf_yield']:.2f} {'>1.3 適合' if v['ok_yield'] else '≦1.3 不適合'}")
			final_y = sf_y-60
			c.setFont(font,12)
			c.drawString(40,final_y, f"総合判定: {'基準を満足する' if (v['ok_break'] and v['ok_yield']) else '基準を満足しない'}")
			# 根拠・考え方
			final_y -= 18
			c.setFont(font,11); c.drawString(40, final_y, '根拠・考え方'); final_y -= 14; c.setFont(font,9)
			c.drawString(45, final_y, '・Z=πd³/32 による丸棒の断面係数、σb=M/Z の基本式を採用。'); final_y -= 12
			c.drawString(45, final_y, '・M は P×ΔS の簡易モデルで算定。荷重分布の詳細は設計条件により補正。'); final_y -= 12
			c.drawString(45, final_y, '・θb と θy を2.5倍荷重下で比較し、破断/降伏の安全率判定を実施。'); final_y -= 12
			c.drawString(45, final_y, '・単位は kg/cm² で統一し、寸法は cm 換算で整合。')
			c.showPage(); c.save()
		except Exception:
			pass


class FrameStrengthPanel(wx.Panel):
	def __init__(self, parent):
		super().__init__(parent)
		v = wx.BoxSizer(wx.VERTICAL)
		# モード選択: 従来6点荷重 / コンテナ4点支持
		self.mode = wx.RadioBox(self, label='計算モード', choices=['従来6点荷重','コンテナ4点支持'], majorDimension=1, style=wx.RA_SPECIFY_ROWS)
		self.mode.SetSelection(1)  # デフォルト: コンテナ4点支持
		self.mode.Bind(wx.EVT_RADIOBOX, self._on_mode_change)
		v.Add(self.mode,0,wx.ALL,4)
		# 図 (旧スタイル) または動的生成
		img_candidates = ['frame_strength.png','frame_strength.jpg','frame_strength.jpeg','images/frame_strength.png']
		img_path=None
		for p in img_candidates:
			if os.path.exists(p): img_path=p; break
		if img_path:
			try:
				img=wx.Image(img_path); max_w=520
				if img.GetWidth()>max_w:
					img=img.Scale(max_w,int(img.GetHeight()*max_w/img.GetWidth()))
				v.Add(wx.StaticBitmap(self,bitmap=wx.BitmapBundle.FromBitmap(wx.Bitmap(img))),0,wx.ALIGN_CENTER|wx.ALL,4)
			except Exception:
				v.Add(wx.StaticText(self,label='図読込失敗'),0,wx.ALL,4)
		else:
			v.Add(self._generate_usage_diagram(),0,wx.ALIGN_CENTER|wx.ALL,4)
			v.Add(wx.StaticText(self,label='(frame_strength.png を配置すると差し替え可)'),0,wx.LEFT|wx.RIGHT|wx.BOTTOM,4)
		# 断面種類選択 (中抜き矩形 / H形鋼)
		self.section_mode = wx.RadioBox(self,label='断面タイプ',choices=['中抜き矩形','H形鋼'],majorDimension=1,style=wx.RA_SPECIFY_ROWS)
		self.section_mode.SetSelection(0)
		self.section_mode.Bind(wx.EVT_RADIOBOX, lambda e: (self._apply_section_visibility(),e.Skip()))
		v.Add(self.section_mode,0,wx.ALL,4)
		# 従来モード入力 (6点荷重 + 5距離)
		self.legacy_panel = wx.Panel(self)
		legacy_s = wx.BoxSizer(wx.VERTICAL)
		self.loads=[]
		grid_load=wx.FlexGridSizer(0,3,4,6)
		for i in range(6):
			grid_load.Add(wx.StaticText(self.legacy_panel,label=f'荷重{i+1}(kg)'),0,wx.ALIGN_CENTER_VERTICAL)
			ctrl=wx.TextCtrl(self.legacy_panel,value='',size=wx.Size(70,-1),style=wx.TE_RIGHT)
			ctrl.SetHint('50')
			self.loads.append(ctrl); grid_load.Add(ctrl,0)
			grid_load.Add(wx.Size(10,10)) if i%2==0 else None
		box_load=wx.StaticBoxSizer(wx.StaticBox(self.legacy_panel,label='荷重入力 (6点)'),wx.VERTICAL)
		box_load.Add(grid_load,0,wx.EXPAND|wx.ALL,4); legacy_s.Add(box_load,0,wx.EXPAND|wx.ALL,4)
		self.dists=[]
		grid_dist=wx.FlexGridSizer(0,2,4,6)
		for i in range(5):
			grid_dist.Add(wx.StaticText(self.legacy_panel,label=f'距離{i+1}(mm)'),0,wx.ALIGN_CENTER_VERTICAL)
			dc=wx.TextCtrl(self.legacy_panel,value='',size=wx.Size(70,-1),style=wx.TE_RIGHT)
			dc.SetHint('500')
			self.dists.append(dc); grid_dist.Add(dc,0)
		box_dist=wx.StaticBoxSizer(wx.StaticBox(self.legacy_panel,label='区間距離 (5区間)'),wx.VERTICAL)
		box_dist.Add(grid_dist,0,wx.EXPAND|wx.ALL,4); legacy_s.Add(box_dist,0,wx.EXPAND|wx.ALL,4)
		self.legacy_panel.SetSizer(legacy_s); v.Add(self.legacy_panel,0,wx.EXPAND|wx.ALL,4)
		# コンテナ4点座 × 支点2点(荷重間) モード入力
		self.container_panel = wx.Panel(self)
		cont_s = wx.BoxSizer(wx.VERTICAL)
		grid_cont = wx.FlexGridSizer(0,2,4,6)
		self.ct_weight = wx.TextCtrl(self.container_panel,value='',style=wx.TE_RIGHT)
		self.ct_weight.SetHint('2800')
		self.ct_span = wx.TextCtrl(self.container_panel,value='',style=wx.TE_RIGHT)
		self.ct_span.SetHint('6000')
		self.ct_coupler_offset = wx.TextCtrl(self.container_panel,value='',style=wx.TE_RIGHT)
		self.ct_coupler_offset.SetHint('800')
		self.ct_coupler_offset.SetToolTip('連結部(カプラ)から縦桁前端までの距離')
		self.ct_front_off = wx.TextCtrl(self.container_panel,value='',style=wx.TE_RIGHT)
		self.ct_front_off.SetHint('600')
		self.ct_rear_off = wx.TextCtrl(self.container_panel,value='',style=wx.TE_RIGHT)
		self.ct_rear_off.SetHint('600')
		self.ct_axle1 = wx.TextCtrl(self.container_panel,value='',style=wx.TE_RIGHT)
		self.ct_axle1.SetHint('2400')
		self.ct_axle1.SetToolTip('サスペンションハンガー中心位置 (前側支点)')
		self.ct_axle2 = wx.TextCtrl(self.container_panel,value='',style=wx.TE_RIGHT)
		self.ct_axle2.SetHint('3600')
		self.ct_axle2.SetToolTip('サスペンションハンガー中心位置 (後側支点)')
		grid_cont.Add(wx.StaticText(self.container_panel,label='コンテナ総重量 W (kg)'),0,wx.ALIGN_CENTER_VERTICAL); grid_cont.Add(self.ct_weight,0,wx.EXPAND)
		grid_cont.Add(wx.StaticText(self.container_panel,label='縦桁全長 L (mm)'),0,wx.ALIGN_CENTER_VERTICAL); grid_cont.Add(self.ct_span,0,wx.EXPAND)
		grid_cont.Add(wx.StaticText(self.container_panel,label='連結部オフセット C (mm) ※カプラ~縦桁前端'),0,wx.ALIGN_CENTER_VERTICAL); grid_cont.Add(self.ct_coupler_offset,0,wx.EXPAND)
		grid_cont.Add(wx.StaticText(self.container_panel,label='前荷重オフセット a (mm)'),0,wx.ALIGN_CENTER_VERTICAL); grid_cont.Add(self.ct_front_off,0,wx.EXPAND)
		grid_cont.Add(wx.StaticText(self.container_panel,label='後荷重オフセット b (mm)'),0,wx.ALIGN_CENTER_VERTICAL); grid_cont.Add(self.ct_rear_off,0,wx.EXPAND)
		grid_cont.Add(wx.StaticText(self.container_panel,label='支点位置 X1 (mm) ※サスペンションハンガー中心'),0,wx.ALIGN_CENTER_VERTICAL); grid_cont.Add(self.ct_axle1,0,wx.EXPAND)
		grid_cont.Add(wx.StaticText(self.container_panel,label='支点位置 X2 (mm) ※サスペンションハンガー中心'),0,wx.ALIGN_CENTER_VERTICAL); grid_cont.Add(self.ct_axle2,0,wx.EXPAND)
		cont_box = wx.StaticBoxSizer(wx.StaticBox(self.container_panel,label='コンテナ4点座 × 支点2点(荷重間) パラメータ'),wx.VERTICAL)
		cont_box.Add(grid_cont,0,wx.EXPAND|wx.ALL,4)
		cont_s.Add(cont_box,0,wx.EXPAND|wx.ALL,4)
		self.container_panel.SetSizer(cont_s); v.Add(self.container_panel,0,wx.EXPAND|wx.ALL,4)
		# 断面寸法パネル: 中抜き矩形
		self.rect_panel = wx.Panel(self)
		rect_s = wx.BoxSizer(wx.VERTICAL)
		self.B=self._dim(rect_s,'外側全幅 B (mm)','','50',parent=self.rect_panel); self.H=self._dim(rect_s,'外側全高さ H (mm)','','102',parent=self.rect_panel)
		self.b=self._dim(rect_s,'内空部幅 b (mm)','','38',parent=self.rect_panel); self.h=self._dim(rect_s,'内空部高さ h (mm)','','90',parent=self.rect_panel)
		self.rect_panel.SetSizer(rect_s); v.Add(self.rect_panel,0,wx.EXPAND|wx.ALL,4)
		# 断面寸法パネル: H形鋼
		self.hbeam_panel = wx.Panel(self)
		hb_s = wx.BoxSizer(wx.VERTICAL)
		self.B_h=self._dim(hb_s,'フランジ幅 B (mm)','','150',parent=self.hbeam_panel); self.H_h=self._dim(hb_s,'全高さ H (mm)','','200',parent=self.hbeam_panel)
		self.tw_h=self._dim(hb_s,'ウェブ厚 tw (mm)','','8',parent=self.hbeam_panel); self.tf_h=self._dim(hb_s,'フランジ厚 tf (mm)','','12',parent=self.hbeam_panel)
		self.hbeam_panel.SetSizer(hb_s); v.Add(self.hbeam_panel,0,wx.EXPAND|wx.ALL,4)
		# 材料
		self.tensile=self._dim(v,'引張強さ θb (kg/cm²)','','410'); self.yield_pt=self._dim(v,'降伏点 θy (kg/cm²)','','240')
		self.yield_pt.SetToolTip('降伏点: 材料が弾性領域を離れて塑性(永久)変形が始まる応力。設計時は降伏点÷安全率以下で使用し永久変形を避けます。')
		self.B.SetToolTip('外側全幅B: 矩形外形左右距離 (mm)')
		self.H.SetToolTip('外側全高さH: 矩形外形上下距離 (mm)')
		self.b.SetToolTip('内空部幅b: 中抜き内部の幅 (mm)')
		self.h.SetToolTip('内空部高さh: 中抜き内部の高さ (mm)')
		self.B_h.SetToolTip('H形鋼フランジ幅 B (mm)')
		self.H_h.SetToolTip('H形鋼全高さ H (mm)')
		self.tw_h.SetToolTip('H形鋼ウェブ厚 tw (mm)')
		self.tf_h.SetToolTip('H形鋼フランジ厚 tf (mm)')
		# ヘルプ
		help_box=wx.StaticBox(self,label='使い方')
		help_s=wx.StaticBoxSizer(help_box,wx.VERTICAL)
		help_txt=(
			'1. 荷重1～6は左から順の下向き荷重(kg)。負値で上向き力。\n'
			'2. 距離1～5は隣接荷重中心間距離(mm)。合計長=L。\n'
			'3. 断面: 中抜き矩形 B,H,b,h。\n'
			'4. 計算: 累積荷重→せん断力→区間曲げモーメント→最大 Mmax。\n'
			'5. 応力 σ = Mmax / Z, Z=(B H³ - b h³)/(6H)。\n'
			'6. 安全率: 破断 >1.6, 降伏 >1.3。PDF出力可。'
		)
		help_ctrl=wx.TextCtrl(help_s.GetStaticBox(),value=help_txt,style=wx.TE_MULTILINE|wx.TE_READONLY|wx.BORDER_NONE,size=wx.Size(-1,110))
		help_ctrl.SetBackgroundColour(self.GetBackgroundColour()); help_s.Add(help_ctrl,1,wx.EXPAND|wx.ALL,4); v.Add(help_s,0,wx.EXPAND|wx.LEFT|wx.RIGHT|wx.TOP,4)
		# ボタン
		btn_row=wx.BoxSizer(wx.HORIZONTAL)
		b_calc=wx.Button(self,label='車枠強度計算'); b_calc.Bind(wx.EVT_BUTTON,self.on_calc); btn_row.Add(b_calc,0,wx.RIGHT,8)
		b_pdf=wx.Button(self,label='PDF出力'); b_pdf.Bind(wx.EVT_BUTTON,self.on_export_pdf); btn_row.Add(b_pdf,0)
		v.Add(btn_row,0,wx.ALIGN_CENTER|wx.ALL,6)
		# グラフは別ウィンドウ表示へ移行したためパネル内では非表示
		# 結果表示 (縦スクロール / 自動折り返し)
		# 結果テキスト領域は撤去（別ウィンドウ出力のみ）
		self.last=None; self.SetSizer(v)
		self._apply_mode_visibility(); self._apply_section_visibility()

	def on_calc(self,_):
		mode_idx = self.mode.GetSelection()
		sec_idx = self.section_mode.GetSelection()  # 0 rect, 1 hbeam
		try:
			if sec_idx==0:
				B=float(self.B.GetValue()); H=float(self.H.GetValue()); b=float(self.b.GetValue()); h=float(self.h.GetValue()); tw=tf=None
			else:
				B=float(self.B_h.GetValue()); H=float(self.H_h.GetValue()); tw=float(self.tw_h.GetValue()); tf=float(self.tf_h.GetValue()); b=h=0.0
			tb=float(self.tensile.GetValue()); ty=float(self.yield_pt.GetValue())
		except ValueError:
			wx.MessageBox('断面/材料入力値を確認してください。','入力エラー',wx.ICON_ERROR); return
		if mode_idx==0:  # 従来
			try:
				weights=[float(c.GetValue()) for c in self.loads]
				dists=[float(c.GetValue()) for c in self.dists]
			except ValueError:
				wx.MessageBox('荷重/距離の数値を確認してください。','入力エラー',wx.ICON_ERROR); return
			try:
				if sec_idx==0:
					res=compute_frame_strength(weights,dists,B,H,b,h,tb,ty)
				else:
					res=compute_frame_strength_hbeam(weights,dists,B,H,tw,tf,tb,ty)
			except ValueError as e:
				wx.MessageBox(str(e),'入力エラー',wx.ICON_ERROR); return
			self.last=dict(mode='legacy',weights=weights,dists=dists,B=B,H=H,b=b,h=h,tw=tw,tf=tf,tb=tb,ty=ty,cross_type=('hbeam' if sec_idx==1 else 'rect'),**res)
			lines=[
				f'◆ 車枠強度計算結果 (従来6点 / {"中抜き矩形" if sec_idx==0 else "H形鋼"}) ◆',
				'[入力]',
				'荷重(kg): ' + ', '.join(f'{w:.1f}' for w in weights),
				'距離(mm): ' + ', '.join(f'{d:.1f}' for d in dists),
				f'断面 B×H / b×h = {B:.1f}×{H:.1f} / {b:.1f}×{h:.1f} mm',
				'',
				'[区間せん断力・曲げモーメント]',
			]
			for i,(s,m) in enumerate(zip(res['shear_list'],res['moment_list'])):
				lines.append(f' 区間{i+1}: せん断={s:.2f} kg  M={m:.2f} kg·cm')
		else:  # コンテナ4点座 × 支点2点(荷重間)
			try:
				cw=float(self.ct_weight.GetValue())
				span=float(self.ct_span.GetValue())
				coupler_offset=float(self.ct_coupler_offset.GetValue())
				front=float(self.ct_front_off.GetValue())
				rear=float(self.ct_rear_off.GetValue())
				ax1=float(self.ct_axle1.GetValue())
				ax2=float(self.ct_axle2.GetValue())
			except ValueError:
				wx.MessageBox('コンテナ重量/スパン/オフセット/支点位置の数値を確認してください。','入力エラー',wx.ICON_ERROR); return
			# 幾何条件検証: a < X1 < X2 < L - b
			lo = front
			hi = (span - rear)
			if lo >= hi:
				wx.MessageBox('a + b が L 以上です。荷重配置を見直してください。','入力エラー',wx.ICON_ERROR); return
			if not (lo < ax1 < ax2 < hi):
				wx.MessageBox(f'支点条件違反: a({front:.1f}) < X1({ax1:.1f}) < X2({ax2:.1f}) < L-b({hi:.1f}) を満たしてください。','入力エラー',wx.ICON_ERROR); return
			try:
				if sec_idx==0:
					res=compute_container_frame_strength_supports_inside(cw, span, front, rear, ax1, ax2, B,H,b,h,tb,ty)
				else:
					res=compute_container_frame_strength_supports_inside_hbeam(cw, span, front, rear, ax1, ax2, B,H,tw,tf,tb,ty)
			except ValueError as e:
				wx.MessageBox(str(e),'入力エラー',wx.ICON_ERROR); return
			# res の型が list[str]|str 推論で float 代入警告が出るため object 辞書へキャスト
			res_obj = cast(dict[str, object], res)
			res_obj['container_weight']=cw; res_obj['span']=span; res_obj['front']=front; res_obj['rear']=rear
			res = res_obj
			# 既存計算関数の mode / cross_type を尊重し保持
			# 既存 dict に追加フィールドのみ付与（mode / cross_type は既存値を尊重）
			self.last = dict(res)  # コピー
			self.last.update(dict(B=B,H=H,b=b,h=h,tw=tw,tf=tf,tb=tb,ty=ty,coupler_offset=coupler_offset))
			lines=[
				f'◆ 車枠強度計算結果 (コンテナ4点座+支点(荷重間) / {"中抜き矩形" if sec_idx==0 else "H形鋼"}) ◆',
				f'コンテナ総重量 = {cw:.1f} kg (縦桁1本 {cw/2.0:.1f} kg)',
				f'連結部オフセット C = {coupler_offset:.1f} mm (カプラ~縦桁前端)',
				f'縦桁全長 L = {span:.1f} mm, 前荷重オフセット a = {front:.1f} mm, 後荷重オフセット b = {rear:.1f} mm',
				f'支点位置 X1 = {ax1:.1f} mm, X2 = {ax2:.1f} mm (a と L-b の間)',
				f'断面 B×H / b×h = {B:.1f}×{H:.1f} / {b:.1f}×{h:.1f} mm',
				'',
				'[区間せん断力・曲げモーメント (縦桁1本換算)]',
				f'R1 = {res['R1']:.2f} kg, R2 = {res['R2']:.2f} kg, P1=P2={res['P1']:.2f} kg',
			]
		# せん断/モーメントリストもキャストして安全に列挙
		shear_list_cast = cast(list[float], res.get('shear_list', []))
		moment_list_cast = cast(list[float], res.get('moment_list', []))
		for i,(s,m) in enumerate(zip(shear_list_cast, moment_list_cast)):
			lines.append(f' 区間{i+1}: せん断={s:.2f} kg  M={m:.2f} kg·cm')
		# 断面係数・応力
		lines += [
			'',
			f"Mmax = {res['Mmax']:.2f} kg·cm",
			f"Z = {res['Z_cm3']:.3f} cm³",
			f"σ = {res['sigma']:.3f} kg/cm²",
			f"破断安全率 = {res['sf_break']:.2f} ({'適' if res['ok_break'] else '否'})",
			f"降伏安全率 = {res['sf_yield']:.2f} ({'適' if res['ok_yield'] else '否'})",
			f"総合判定: {'基準適合' if (res['ok_break'] and res['ok_yield']) else '基準不適合'}",
		]
		if sec_idx==1:
			lines.append('断面係数式: Z = 2/ H × [B H³ - (B - tw) (H - 2 tf)³] / 12')
		else:
			lines.append('断面係数式: Z = (B H³ - b h³)/(6 H)')
		show_result('車枠強度計算結果', '\n'.join(lines))
		# show_frame_graph(self.last)  # グラフウィンドウは非表示

	def on_export_pdf(self,_):
		if self.last is None:
			wx.MessageBox('先に計算を実行してください。','PDF出力',wx.ICON_INFORMATION); return
		if not _REPORTLAB_AVAILABLE:
			wx.MessageBox('ReportLabが未インストールです。','PDF出力不可',wx.ICON_ERROR); return
		with wx.FileDialog(self,message='PDF保存',wildcard='PDF files (*.pdf)|*.pdf',style=wx.FD_SAVE|wx.FD_OVERWRITE_PROMPT,defaultFile='車枠強度計算書.pdf') as dlg:
			if dlg.ShowModal()!=wx.ID_OK: return
			path=dlg.GetPath()
		try:
			# 1) Canvas とフォント
			c=_pdf_canvas.Canvas(path,pagesize=_A4)
			W,H=_A4
			font='Helvetica'
			for f in ['C:/Windows/Fonts/msgothic.ttc', 'C:/Windows/Fonts/meiryo.ttc', 'C:/Windows/Fonts/yugothic.ttf', 'ipaexg.ttf','ipaexm.ttf','fonts/ipaexg.ttf','fonts/ipaexm.ttf']:
				if os.path.exists(f):
					try:
						_pdfmetrics.registerFont(_TTFont('JPFrame',f)); font='JPFrame'; break
					except Exception:
						pass
			# 2) 余白とレイアウトユーティリティ
			left=40; right=40; top=40; bottom=50
			y=H-top
			c.setFont(font,13)
			c.drawString(left, y, '車枠強度計算書')
			y -= 18
			c.setFont(font,9)
			v=self.last
			# コンテナモードなら4点座配置図を最初に挿入
			mode=str(v.get('mode','legacy'))
			if mode in ('container4','container4_axles','container4_supports_inside','container'):
				span=cast(float,v.get('span',v.get('span_len_mm',0.0)))
				front=cast(float,v.get('front',v.get('front_offset_mm',0.0)))
				rear=cast(float,v.get('rear',v.get('rear_offset_mm',0.0)))
				ax1=cast(float,v.get('axle1_pos_mm',v.get('X1',0.0)))
				ax2=cast(float,v.get('axle2_pos_mm',v.get('X2',0.0)))
				coupler_off=cast(float,v.get('coupler_offset',0.0))
				seating_diagram = ''
				try:
					seating_diagram = create_container_seating_diagram_png(span, front, rear, ax1, ax2, coupler_off)
				except Exception:
					pass
				if seating_diagram:
					try:
						img_w=600; img_h=190
						c.drawImage(seating_diagram, left - 20, y-img_h, width=img_w, height=img_h, preserveAspectRatio=True, mask='auto')
						y -= img_h + 8
					except Exception:
						pass
			# ヘルパ: 改ページ判定
			def ensure_space(h_needed: float):
				nonlocal y
				if y - h_needed < bottom:
					c.showPage()
					c.setFont(font,10)
					y = H - top
					return True
				return False
			# ヘルパ: ボックス見出し
			def section(title: str, gap: int=6):
				nonlocal y
				ensure_space(18)
				c.setFont(font,10)
				c.drawString(left, y, title)
				y -= gap + 3
				c.setFont(font,9)
			# ヘルパ: 単純表 (ラベル, 値, 単位)
			def simple_table(rows: list[tuple[str,str,str]], colw=(150,85,55), row_h=13):
				nonlocal y
				Wtot=sum(colw); Ht=row_h*len(rows)
				ensure_space(Ht+6)
				c.rect(left, y-Ht, Wtot, Ht)
				# 横線
				for i in range(1,len(rows)):
					c.line(left, y-row_h*i, left+Wtot, y-row_h*i)
				# 縦線
				cx=left
				for wcol in colw[:-1]:
					cx += wcol
					c.line(cx, y, cx, y-Ht)
				# 文字
				for r,(lab,val,unit) in enumerate(rows):
					cy = y - row_h*(r+1) + 3
					c.drawString(left+4, cy, lab)
					c.drawRightString(left+colw[0]+colw[1]-6, cy, val)
					c.drawString(left+colw[0]+colw[1]+5, cy, unit)
				y -= Ht + 8
			# ヘルパ: 2列×3カラム表 (項目/値/単位 ×2)
			def grid_2x(rows: list[list[str]], colw=(55,55,40, 55,55,40), row_h=13):
				nonlocal y
				Wtot=sum(colw); Ht=row_h*len(rows)
				ensure_space(Ht+6)
				c.rect(left, y-Ht, Wtot, Ht)
				for i in range(1,len(rows)):
					c.line(left, y-row_h*i, left+Wtot, y-row_h*i)
				cx=left
				for wcol in colw[:-1]:
					cx += wcol
					c.line(cx, y, cx, y-Ht)
				for r,row in enumerate(rows):
					cy=y-row_h*(r+1)+3
					cx=left+4
					for i,val in enumerate(row):
						c.drawString(cx, cy, str(val))
						cx += colw[i]
				y -= Ht + 8
			# 3) 入力諸元
			B=cast(float,v.get('B',0)); Hs=cast(float,v.get('H',0)); bb=cast(float,v.get('b',0)); hh=cast(float,v.get('h',0))
			tw=cast(float,v.get('tw',0)); tf=cast(float,v.get('tf',0)); tb=cast(float,v.get('tb',0)); ty=cast(float,v.get('ty',0))
			cross_type=str(v.get('cross_type','rect'))
			section('入力諸元')
			if cross_type=='hbeam':
				grid_2x([
					['B', f"{B:.1f}", 'mm', 'H', f"{Hs:.1f}", 'mm'],
					['tw', f"{tw:.1f}", 'mm', 'tf', f"{tf:.1f}", 'mm'],
					['θb', f"{tb:.1f}", 'kg/cm²', 'θy', f"{ty:.1f}", 'kg/cm²'],
				])
			else:
				grid_2x([
					['B', f"{B:.1f}", 'mm', 'H', f"{Hs:.1f}", 'mm'],
					['b', f"{bb:.1f}", 'mm', 'h', f"{hh:.1f}", 'mm'],
					['θb', f"{tb:.1f}", 'kg/cm²', 'θy', f"{ty:.1f}", 'kg/cm²'],
				])
			# 断面図を追加
			section('断面図')
			ensure_space(130)
			cross_diagram = ''
			try:
				cross_diagram = create_cross_section_diagram_png(B, Hs, bb, hh, tw, tf, cross_type)
			except Exception:
				pass
			if cross_diagram:
				try:
					img_w=180; img_h=180
					c.drawImage(cross_diagram, left - 20, y-img_h, width=img_w, height=img_h, preserveAspectRatio=True, mask='auto')
					y -= img_h + 8
				except Exception:
					pass
			else:
				y -= 6
			y -= 6  # 断面図の後に少し間隔を追加
			mode=str(v.get('mode','legacy'))
			if mode in ('container4','container4_axles','container4_supports_inside','container'):
				cw=cast(float,v.get('container_weight',0.0))
				span=cast(float,v.get('span',v.get('span_len_mm',0.0)))
				coupler_off=cast(float,v.get('coupler_offset',0.0))
				front=cast(float,v.get('front',v.get('front_offset_mm',0.0)))
				rear=cast(float,v.get('rear',v.get('rear_offset_mm',0.0)))
				ax1=cast(float,v.get('axle1_pos_mm',v.get('X1',0.0)))
				ax2=cast(float,v.get('axle2_pos_mm',v.get('X2',0.0)))
				rows=[('コンテナ総重量', f"{cw:.1f}", 'kg'), ('縦桁全長 L', f"{span:.1f}", 'mm'), ('連結部オフセット C', f"{coupler_off:.1f}", 'mm'), ('前オフセット a', f"{front:.1f}", 'mm'), ('後オフセット b', f"{rear:.1f}", 'mm')]
				if ax2>0:
					rows += [('支点位置 X1', f"{ax1:.1f}", 'mm'), ('支点位置 X2', f"{ax2:.1f}", 'mm')]
				section('支持・荷重配置')
				simple_table(rows)
			else:
				# 従来モード: 荷重・距離一覧
				weights=cast(list[float], v.get('weights', []))
				dists=cast(list[float], v.get('dists', []))
				section('荷重・距離一覧')
				rows=[(f'荷重{i+1}', f"{w:.1f}", 'kg') for i,w in enumerate(weights)] + [(f'距離{i+1}', f"{d:.1f}", 'mm') for i,d in enumerate(dists)]
				simple_table(rows)
				y -= 6  # 支持・荷重配置の後に間隔を追加
			# 4) 結果サマリ
			Mmax=cast(float,v.get('Mmax',0.0)); Zcm3=cast(float,v.get('Z_cm3',0.0)); sigma=cast(float,v.get('sigma',0.0))
			sf_b=cast(float,v.get('sf_break',0.0)); sf_y=cast(float,v.get('sf_yield',0.0))
			ok_b=bool(v.get('ok_break', False)); ok_y=bool(v.get('ok_yield', False))
			section('計算結果サマリ')
			rows_sum=[('Mmax(最大曲げモーメント)', f"{Mmax:.2f}", 'kg·cm'), ('Z(断面係数)', f"{Zcm3:.3f}", 'cm³'), ('σ(曲げ応力)', f"{sigma:.3f}", 'kg/cm²'), ('破断安全率', f"{sf_b:.2f}", '>=1.6' if sf_b else ''), ('降伏安全率', f"{sf_y:.2f}", '>=1.3' if sf_y else '')]
			simple_table(rows_sum)
			# 記号の意味を補足
			c.setFont(font,8)
			c.drawString(left, y, '記号の意味: Mmax=最大曲げモーメント, Z=断面係数, σ=曲げ応力, θb=引張強さ, θy=降伏点')
			y -= 6
			y -= 10  # 計算結果サマリの後の間隔を少し拡大
			# 5) 計算式
			section('計算式')
			ensure_space(54)
			c.setFont(font,8)
			c.drawString(left, y, '・Mmax: 区間曲げモーメントの最大値')
			y -= 9
			if cross_type=='hbeam':
				c.drawString(left, y, '・Z: 2I/H,  I = (B H³ - (B - tw)(H - 2tf)³) / 12')
			else:
				c.drawString(left, y, '・Z: (B H³ - b h³) / (6 H)')
			y -= 9
			c.drawString(left, y, '・σ: Mmax / Z')
			y -= 9
			c.drawString(left, y, '・破断安全率: θb / (2.5 × σ)')
			y -= 9
			c.drawString(left, y, '・降伏安全率: θy / (2.5 × σ)')
			y -= 10
			c.setFont(font,10)
			c.drawString(left, y, f"総合判定: {'基準を満たす' if (ok_b and ok_y) else '基準を満たさない'}")
			y -= 24
			# 6) コンテナモードの場合、4点座位置表を左右縦桁別に追加
			if mode in ('container4','container4_axles','container4_supports_inside','container'):
				section('4点座位置 (左右縦桁それぞれ)')
				ensure_space(55)
				c.setFont(font,8)
				cw=cast(float,v.get('container_weight',0.0))
				span=cast(float,v.get('span',v.get('span_len_mm',0.0)))
				coupler_off=cast(float,v.get('coupler_offset',0.0))
				front=cast(float,v.get('front',v.get('front_offset_mm',0.0)))
				rear=cast(float,v.get('rear',v.get('rear_offset_mm',0.0)))
				# 1縦桁当たり荷重 (総重量 / 2)
				load_per_beam = cw / 2.0
				load_per_seat = load_per_beam / 2.0
				# カプラ基準の位置
				front_from_coupler = coupler_off + front
				rear_from_coupler = coupler_off + (span - rear)
				c.drawString(left, y, f'左側縦桁: 前座 (カプラから{front_from_coupler:.1f} mm), 後座 (カプラから{rear_from_coupler:.1f} mm) [各座荷重 {load_per_seat:.1f} kg]')
				y -= 11
				c.drawString(left, y, f'右側縦桁: 前座 (カプラから{front_from_coupler:.1f} mm), 後座 (カプラから{rear_from_coupler:.1f} mm) [各座荷重 {load_per_seat:.1f} kg]')
				y -= 11
				c.drawString(left, y, f'※ 左右縦桁合計4点座, 各座荷重合計 = {cw:.1f} kg')
				y -= 12
			# 保存
			c.save()
			try:
				_open_saved_pdf(path)
			except Exception:
				pass
			wx.MessageBox('PDFを保存し開きました。','完了',wx.ICON_INFORMATION)
		except Exception as e:
			wx.MessageBox(f'PDF出力中エラー: {e}','エラー',wx.ICON_ERROR)

	def get_state(self):
		state = {
			'mode': self.mode.GetSelection(),
			'section_mode': self.section_mode.GetSelection(),
			'B': self.B.GetValue(),
			'H': self.H.GetValue(),
			'b': self.b.GetValue(),
			'h': self.h.GetValue(),
			'B_h': self.B_h.GetValue(),
			'H_h': self.H_h.GetValue(),
			'tw_h': self.tw_h.GetValue(),
			'tf_h': self.tf_h.GetValue(),
			'tensile': self.tensile.GetValue(),
			'yield_pt': self.yield_pt.GetValue(),
			'last': self.last
		}
		if self.mode.GetSelection() == 0:
			state['loads'] = [c.GetValue() for c in self.loads]
			state['dists'] = [c.GetValue() for c in self.dists]
		else:
			state['ct_weight'] = self.ct_weight.GetValue()
			state['ct_span'] = self.ct_span.GetValue()
			state['ct_coupler_offset'] = self.ct_coupler_offset.GetValue()
			state['ct_front_off'] = self.ct_front_off.GetValue()
			state['ct_rear_off'] = self.ct_rear_off.GetValue()
			state['ct_axle1'] = self.ct_axle1.GetValue()
			state['ct_axle2'] = self.ct_axle2.GetValue()
		return state

	def set_state(self, state):
		if not state:
			return
		if 'mode' in state:
			self.mode.SetSelection(state['mode'])
			self._apply_mode_visibility()
		if 'section_mode' in state:
			self.section_mode.SetSelection(state['section_mode'])
			self._apply_section_visibility()
		if 'B' in state:
			self.B.SetValue(str(state['B']))
		if 'H' in state:
			self.H.SetValue(str(state['H']))
		if 'b' in state:
			self.b.SetValue(str(state['b']))
		if 'h' in state:
			self.h.SetValue(str(state['h']))
		if 'B_h' in state:
			self.B_h.SetValue(str(state['B_h']))
		if 'H_h' in state:
			self.H_h.SetValue(str(state['H_h']))
		if 'tw_h' in state:
			self.tw_h.SetValue(str(state['tw_h']))
		if 'tf_h' in state:
			self.tf_h.SetValue(str(state['tf_h']))
		if 'tensile' in state:
			self.tensile.SetValue(str(state['tensile']))
		if 'yield_pt' in state:
			self.yield_pt.SetValue(str(state['yield_pt']))
		if 'loads' in state:
			for i, val in enumerate(state['loads']):
				if i < len(self.loads):
					self.loads[i].SetValue(str(val))
		if 'dists' in state:
			for i, val in enumerate(state['dists']):
				if i < len(self.dists):
					self.dists[i].SetValue(str(val))
		if 'ct_weight' in state:
			self.ct_weight.SetValue(str(state['ct_weight']))
		if 'ct_span' in state:
			self.ct_span.SetValue(str(state['ct_span']))
		if 'ct_coupler_offset' in state:
			self.ct_coupler_offset.SetValue(str(state['ct_coupler_offset']))
		if 'ct_front_off' in state:
			self.ct_front_off.SetValue(str(state['ct_front_off']))
		if 'ct_rear_off' in state:
			self.ct_rear_off.SetValue(str(state['ct_rear_off']))
		if 'ct_axle1' in state:
			self.ct_axle1.SetValue(str(state['ct_axle1']))
		if 'ct_axle2' in state:
			self.ct_axle2.SetValue(str(state['ct_axle2']))
		if 'last' in state:
			self.last = state['last']

	def export_to_path(self, path):
		if self.last is None or not _REPORTLAB_AVAILABLE:
			return
		try:
			c=_pdf_canvas.Canvas(path,pagesize=_A4)
			W,H=_A4
			font='Helvetica'
			for f in ['C:/Windows/Fonts/msgothic.ttc', 'C:/Windows/Fonts/meiryo.ttc', 'C:/Windows/Fonts/yugothic.ttf', 'ipaexg.ttf','ipaexm.ttf','fonts/ipaexg.ttf','fonts/ipaexm.ttf']:
				if os.path.exists(f):
					try:
						_pdfmetrics.registerFont(_TTFont('JPFrame',f)); font='JPFrame'; break
					except Exception:
						pass
			left=40; right=40; top=40; bottom=50
			y=H-top
			c.setFont(font,13)
			c.drawString(left, y, '車枠強度計算書')
			y -= 18
			c.setFont(font,9)
			v=self.last
			mode=str(v.get('mode','legacy'))
			cross_type=str(v.get('cross_type','rect'))
			c.setFont(font,9)
			c.drawString(left,y,f"計算モード: {'従来' if mode=='legacy' else 'コンテナ'}, 断面: {'中抜き矩形' if cross_type=='rect' else 'H形鋼'}"); y-=14
			def section(title):
				nonlocal y
				y-=10; c.setFont(font,10); c.drawString(left,y,title); y-=12; c.setFont(font,8)
			def simple_table(rows):
				nonlocal y
				rh=14; cw=[140,100,80]
				for r in rows:
					cx=left
					for j,cell in enumerate(r):
						c.drawString(cx,y,str(cell)); cx+=cw[j]
					y-=rh
				y-=6
			def ensure_space(needed):
				nonlocal y
				if y < bottom+needed:
					c.showPage(); y=H-top; c.setFont(font,9)
			section('断面寸法')
			ensure_space(60)
			if cross_type=='rect':
				rows=[('B(外側全幅)', f"{v.get('B',0):.1f}", 'mm'), ('H(外側全高さ)', f"{v.get('H',0):.1f}", 'mm'), ('b(内空部幅)', f"{v.get('b',0):.1f}", 'mm'), ('h(内空部高さ)', f"{v.get('h',0):.1f}", 'mm')]
			else:
				rows=[('B(フランジ幅)', f"{v.get('B',0):.1f}", 'mm'), ('H(全高さ)', f"{v.get('H',0):.1f}", 'mm'), ('tw(ウェブ厚)', f"{v.get('tw',0):.1f}", 'mm'), ('tf(フランジ厚)', f"{v.get('tf',0):.1f}", 'mm')]
			simple_table(rows)
			section('材料')
			ensure_space(40)
			rows=[('引張強さ θb', f"{v.get('tb',0):.1f}", 'kg/cm²'), ('降伏点 θy', f"{v.get('ty',0):.1f}", 'kg/cm²')]
			simple_table(rows)
			Mmax=cast(float,v.get('Mmax',0.0)); Zcm3=cast(float,v.get('Z_cm3',0.0)); sigma=cast(float,v.get('sigma',0.0))
			sf_b=cast(float,v.get('sf_break',0.0)); sf_y=cast(float,v.get('sf_yield',0.0))
			ok_b=bool(v.get('ok_break', False)); ok_y=bool(v.get('ok_yield', False))
			section('計算結果サマリ')
			ensure_space(80)
			rows_sum=[('Mmax(最大曲げモーメント)', f"{Mmax:.2f}", 'kg·cm'), ('Z(断面係数)', f"{Zcm3:.3f}", 'cm³'), ('σ(曲げ応力)', f"{sigma:.3f}", 'kg/cm²'), ('破断安全率', f"{sf_b:.2f}", '>=1.6' if sf_b else ''), ('降伏安全率', f"{sf_y:.2f}", '>=1.3' if sf_y else '')]
			simple_table(rows_sum)
			c.setFont(font,10)
			c.drawString(left, y, f"総合判定: {'基準を満たす' if (ok_b and ok_y) else '基準を満たさない'}")
			# 根拠・考え方
			y -= 16
			c.setFont(font,10); c.drawString(left, y, '根拠・考え方'); y -= 14; c.setFont(font,8)
			c.drawString(left+5, y, '・断面係数 Z は断面形状に応じた式を用いる（矩形: (B H³ − b h³)/(6H)、H形鋼: Z=2I/H）。'); y -= 12
			c.drawString(left+5, y, '・最大曲げモーメント Mmax は荷重配置に基づく区間の最大値を採用。'); y -= 12
			c.drawString(left+5, y, '・曲げ応力 σ は σ=Mmax/Z、材質の引張強さ θb と降伏点 θy で安全率を評価。'); y -= 12
			c.drawString(left+5, y, '・安全側の設計目安として荷重倍率2.5を採用し、基準(破断≥1.6/降伏≥1.3)で判定。'); y -= 12
			c.save()
		except Exception:
			pass

	def _on_mode_change(self,_):
		self._apply_mode_visibility()

	def _apply_mode_visibility(self):
		legacy = (self.mode.GetSelection()==0)
		self.legacy_panel.Show(legacy)
		self.container_panel.Show(not legacy)
		self.Layout()

	def _apply_section_visibility(self):
		is_rect = (self.section_mode.GetSelection()==0)
		self.rect_panel.Show(is_rect)
		self.hbeam_panel.Show(not is_rect)
		self.Layout()

 

	def _generate_usage_diagram(self):
		w,h = 560,170
		bmp = wx.Bitmap(w,h)
		dc = wx.MemoryDC(bmp)
		dc.SetBackground(wx.Brush(wx.Colour(255,255,255)))
		dc.Clear()
		# タイトル
		dc.SetTextForeground(wx.Colour(0,0,0))
		dc.SetFont(wx.Font(10, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL))
		dc.DrawText('車枠強度: 荷重配置/距離入力イメージ',10,5)
		# 梁
		beam_y = 90
		dc.SetPen(wx.Pen(wx.Colour(0,0,0),2))
		dc.DrawLine(40,beam_y,520,beam_y)
		# 支点 (簡易三角)
		def support(x):
			pts = [wx.Point(x-12,beam_y), wx.Point(x,beam_y+20), wx.Point(x+12,beam_y)]
			dc.SetBrush(wx.Brush(wx.Colour(180,180,180)))
			dc.DrawPolygon(pts)
		support(40); support(520)
		# 荷重 6点 (例) 等間隔
		load_count = 6
		spacing = (520-40)/(load_count+1)
		arrow_color = wx.Colour(220,0,0)
		dc.SetPen(wx.Pen(arrow_color,2))
		dc.SetBrush(wx.Brush(arrow_color))
		positions = []
		for i in range(load_count):
			x = int(40 + spacing*(i+1))
			positions.append(x)
			# 矢印 (下向き)
			dc.DrawLine(x, beam_y-45, x, beam_y)
			dc.DrawPolygon([wx.Point(x-6,beam_y-10), wx.Point(x+6,beam_y-10), wx.Point(x,beam_y)])
			dc.SetTextForeground(arrow_color)
			dc.DrawText(f'荷重{i+1}', x-22, beam_y-60)
		# 距離ラベル
		dc.SetTextForeground(wx.Colour(0,0,150))
		dc.SetFont(wx.Font(9, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL))
		for i in range(load_count-1):
			x1 = positions[i]; x2 = positions[i+1]
			mid = (x1+x2)//2
			# 寸法線
			dc.SetPen(wx.Pen(wx.Colour(0,0,150),1,wx.PENSTYLE_LONG_DASH))
			dc.DrawLine(x1, beam_y+8, x1, beam_y+28)
			dc.DrawLine(x2, beam_y+8, x2, beam_y+28)
			dc.DrawLine(x1, beam_y+20, x2, beam_y+20)
			dc.DrawText(f'距離{i+1}', mid-18, beam_y+32)
		# 説明
		dc.SetPen(wx.Pen(wx.Colour(0,0,0),1))
		dc.SetTextForeground(wx.Colour(0,0,0))
		dc.SetFont(wx.Font(8, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL))
		dc.DrawText('荷重は左端から順に 荷重1～6 を入力。距離1～5 は隣接荷重中心間距離(mm)。',10,140)
		dc.SelectObject(wx.NullBitmap)
		return wx.StaticBitmap(self, bitmap=wx.BitmapBundle.FromBitmap(bmp))

	def _dim(self, sizer, label, default='', hint='', parent=None):
		# sizer が紐づくコンテナ (Panel) を親として部品生成することで
		# SetSizer されたパネルと子ウィンドウ親が一致し wxSizer のアサートを防ぐ。
		if parent is None:
			parent = getattr(sizer, 'GetContainingWindow', lambda: None)() or self
		h = wx.BoxSizer(wx.HORIZONTAL)
		h.Add(wx.StaticText(parent,label=label),0,wx.RIGHT|wx.ALIGN_CENTER_VERTICAL,6)
		ctrl = wx.TextCtrl(parent,value=default,size=wx.Size(80,-1),style=wx.TE_RIGHT)
		if hint:
			ctrl.SetHint(hint)
		h.Add(ctrl,0)
		sizer.Add(h,0,wx.EXPAND|wx.LEFT|wx.RIGHT|wx.TOP,4)
		return ctrl



class BrakeStrengthPanel(wx.Panel):
	"""制動装置（ブレーキドラム）強度計算パネル"""
	def __init__(self, parent):
		super().__init__(parent)
		self.last = None
		
		main_sizer = wx.BoxSizer(wx.VERTICAL)
		
		# タイトル
		title = wx.StaticText(self, label='制動装置（ブレーキドラム）強度計算')
		title_font = title.GetFont()
		title_font.PointSize += 3
		title_font = title_font.Bold()
		title.SetFont(title_font)
		main_sizer.Add(title, 0, wx.ALL, 10)
		
		# 図描画パネル & 基準値表示
		figure_sizer = wx.BoxSizer(wx.HORIZONTAL)
		
		# 図描画エリア
		self.diagram = wx.Panel(self, size=wx.Size(200, 200))
		self.diagram.SetBackgroundColour(wx.Colour(245, 245, 245))
		self.diagram.Bind(wx.EVT_PAINT, self.on_paint_diagram)
		figure_sizer.Add(self.diagram, 0, wx.ALL|wx.EXPAND, 5)
		
		# 基準値・説明テキスト
		info_sizer = wx.BoxSizer(wx.VERTICAL)
		info_text = wx.StaticText(self, label='【ブレーキドラム強度計算】\n\nブレーキドラム（円筒形）に\n内部から圧力が加わった時の\n強度を計算します。\n\n[安全率の基準]\n・引張強さ: >= 1.6倍\n・降伏点: >= 1.6倍\n・せん断強さ: >= 1.6倍\n\nすべての条件を満たせば「合格」\nです。')
		info_text.SetFont(wx.Font(9, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL))
		info_sizer.Add(info_text, 1, wx.ALL|wx.EXPAND, 5)
		figure_sizer.Add(info_sizer, 1, wx.ALL|wx.EXPAND, 5)
		
		main_sizer.Add(figure_sizer, 0, wx.EXPAND|wx.ALL, 5)
		
		# スクロール & グリッド
		scroll = wx.ScrolledWindow(self, style=wx.VSCROLL)
		scroll.SetScrollRate(0, 20)
		scroll_sizer = wx.BoxSizer(wx.VERTICAL)
		
		# 寸法セクション
		self._add_section(scroll_sizer, "寸法 (mm)", scroll)
		self.r_inner = self._add(scroll_sizer, 'ドラム内径 (mm)', '210', scroll)
		self.r_outer = self._add(scroll_sizer, 'ドラム外径 (mm)', '230', scroll)
		self.width = self._add(scroll_sizer, 'ドラム幅 (mm)', '50', scroll)
		
		# 圧力セクション
		self._add_section(scroll_sizer, "ブレーキ内圧 (MPa)", scroll)
		self.pressure = self._add(scroll_sizer, '最大作用圧力 (MPa)', '25', scroll)
		
		# 材料セクション
		self._add_section(scroll_sizer, "材料強度 (N/mm2)", scroll)
		self.tensile = self._add(scroll_sizer, '引張強さ (N/mm2)', '1000', scroll)
		self.yield_pt = self._add(scroll_sizer, '降伏点 (N/mm2)', '850', scroll)
		self.shear = self._add(scroll_sizer, 'せん断強さ (N/mm2)', '600', scroll)
		
		scroll.SetSizer(scroll_sizer)
		main_sizer.Add(scroll, 1, wx.EXPAND|wx.ALL, 5)
		
		# ボタン
		btn_sizer = wx.BoxSizer(wx.HORIZONTAL)
		
		btn_calc = wx.Button(self, label='計算')
		btn_calc.Bind(wx.EVT_BUTTON, self.on_calc)
		btn_sizer.Add(btn_calc, 0, wx.ALL, 5)
		
		btn_preview = wx.Button(self, label='プレビュー')
		btn_preview.Bind(wx.EVT_BUTTON, self.on_preview)
		btn_sizer.Add(btn_preview, 0, wx.ALL, 5)
		
		btn_export = wx.Button(self, label='PDF出力...')
		btn_export.Bind(wx.EVT_BUTTON, self.on_export)
		btn_sizer.Add(btn_export, 0, wx.ALL, 5)
		
		main_sizer.Add(btn_sizer, 0, wx.EXPAND|wx.ALL, 10)
		self.SetSizer(main_sizer)
	
	def _add_section(self, sizer, title, parent):
		"""セクションタイトルを追加"""
		label = wx.StaticText(parent, label=title)
		font = label.GetFont()
		font.PointSize += 1
		font = font.Bold()
		label.SetFont(font)
		sizer.Add(label, 0, wx.ALL|wx.TOP, 10)
		sizer.Add(wx.StaticLine(parent), 0, wx.EXPAND|wx.LEFT|wx.RIGHT, 5)
	
	def _add(self, sizer, label, default='', parent=None):
		"""入力フィールドを追加"""
		h_sizer = wx.BoxSizer(wx.HORIZONTAL)
		label_widget = wx.StaticText(parent or self, label=label, size=wx.Size(100, -1))
		h_sizer.Add(label_widget, 0, wx.ALIGN_CENTER_VERTICAL|wx.ALL, 5)
		
		text_ctrl = wx.TextCtrl(parent or self, value=default, size=wx.Size(150, -1))
		h_sizer.Add(text_ctrl, 0, wx.ALL, 5)
		
		sizer.Add(h_sizer, 0, wx.EXPAND)
		return text_ctrl
	
	def on_calc(self, _):
		"""計算実行"""
		try:
			r_inner = float(self.r_inner.GetValue())
			r_outer = float(self.r_outer.GetValue())
			width = float(self.width.GetValue())
			pressure = float(self.pressure.GetValue())
			tensile = float(self.tensile.GetValue())
			yield_pt = float(self.yield_pt.GetValue())
			shear = float(self.shear.GetValue())
			
			if r_inner <= 0 or r_outer <= 0 or width <= 0 or pressure < 0:
				raise ValueError('正の値を入力してください')
			if r_inner >= r_outer:
				raise ValueError('外径は内径より大きくしてください')
			
			self.last = compute_brake_drum_strength(
				r_inner, r_outer, pressure, width,
				tensile, yield_pt, shear
			)
			
			# 図を更新
			self.diagram.Refresh()
			
			text = format_brake_strength_result(self.last)
			# 基準値情報を追加表示
			text += f"\n[安全率基準] 引張/降伏/せん断 >= {self.last['min_safety_required']:.1f}"
			show_result('制動装置強度計算結果', text)
		
		except ValueError as e:
			wx.MessageBox(f'入力エラー: {e}', 'エラー', wx.ICON_ERROR)
	
	def on_preview(self, _):
		"""プレビュー"""
		try:
			if not self.last:
				wx.MessageBox('先に「計算」を実行してください', 'プレビュー', wx.ICON_INFORMATION)
				return
			text = format_brake_strength_result(self.last)
			# 基準値情報を追加表示
			text += f"\n[安全率基準] 引張/降伏/せん断 >= {self.last['min_safety_required']:.1f}"
			show_result('制動装置強度 プレビュー', text)
		except Exception as e:
			wx.MessageBox(f'プレビューエラー: {e}', 'エラー', wx.ICON_ERROR)
	
	def on_export(self, _):
		"""PDF出力"""
		if not _REPORTLAB_AVAILABLE:
			wx.MessageBox('ReportLabがインストールされていません', 'PDF出力不可', wx.ICON_ERROR)
			return
		
		with wx.FileDialog(self, 'PDF保存',
						   wildcard='PDF files (*.pdf)|*.pdf',
						   style=wx.FD_SAVE|wx.FD_OVERWRITE_PROMPT,
						   defaultFile='制動装置強度計算.pdf') as dlg:
			if dlg.ShowModal() != wx.ID_OK:
				return
			output_path = dlg.GetPath()
		
		try:
			if not self.last:
				wx.MessageBox('先に「計算」を実行してください', 'エラー', wx.ICON_ERROR)
				return
			
			self._export_pdf(output_path)
			wx.MessageBox(f'PDFを保存しました:\n{output_path}', '完了', wx.ICON_INFORMATION)
			
			# PDF を自動で開く
			import os
			try:
				os.startfile(output_path)
			except:
				pass
		except Exception as e:
			wx.MessageBox(f'PDF出力エラー: {e}', 'エラー', wx.ICON_ERROR)
	
	def on_paint_diagram(self, event):
		"""図の描画"""
		dc = wx.PaintDC(self.diagram)
		dc.SetBackground(wx.Brush(wx.Colour(245, 245, 245)))
		dc.Clear()
		
		# サイズ取得
		w, h = self.diagram.GetSize()
		cx, cy = w // 2, h // 2
		
		try:
			# 外径円
			outer_r = 50
			dc.SetPen(wx.Pen(wx.BLACK, 2))
			dc.SetBrush(wx.Brush(wx.Colour(200, 220, 250)))
			dc.DrawCircle(cx, cy, outer_r)
			
			# 内径円
			inner_r = 35
			dc.SetPen(wx.Pen(wx.BLACK, 2))
			dc.SetBrush(wx.Brush(wx.WHITE))
			dc.DrawCircle(cx, cy, inner_r)
			
			# 内圧矢印（4方向）
			dc.SetPen(wx.Pen(wx.RED, 2))
			arrow_len = 15
			for angle in [0, 90, 180, 270]:
				import math
				rad = math.radians(angle)
				start_x = cx + inner_r * math.cos(rad)
				start_y = cy + inner_r * math.sin(rad)
				end_x = cx + (inner_r + arrow_len) * math.cos(rad)
				end_y = cy + (inner_r + arrow_len) * math.sin(rad)
				dc.DrawLine(int(start_x), int(start_y), int(end_x), int(end_y))
				# 矢印先端
				dc.DrawPolygon([(int(end_x), int(end_y)), 
							   (int(end_x - 3 * math.cos(rad) - 3 * math.sin(rad)), int(end_y - 3 * math.sin(rad) + 3 * math.cos(rad))),
							   (int(end_x - 3 * math.cos(rad) + 3 * math.sin(rad)), int(end_y - 3 * math.sin(rad) - 3 * math.cos(rad)))])
			
			# ラベル
			dc.SetFont(wx.Font(8, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD))
			try:
				r_inner_val = float(self.r_inner.GetValue())
				r_outer_val = float(self.r_outer.GetValue())
				dc.DrawText(f"内径:{r_inner_val:.0f}mm", cx - 40, cy + outer_r + 5)
				dc.DrawText(f"外径:{r_outer_val:.0f}mm", cx - 40, cy - outer_r - 20)
				dc.DrawText("内圧(赤矢印)", cx - 35, cy - 10)
			except:
				pass
		except:
			pass
	
	def _export_pdf(self, path):
		"""PDF出力処理"""
		if not self.last:
			return
		
		from reportlab.pdfgen import canvas
		from reportlab.lib.pagesizes import A4
		from reportlab.pdfbase import pdfmetrics
		from reportlab.pdfbase.ttfonts import TTFont
		
		try:
			pdfmetrics.registerFont(TTFont('Japanese', 'C:/Windows/Fonts/msgothic.ttc'))
			font = 'Japanese'
		except:
			font = 'Helvetica'
		
		c = canvas.Canvas(path, pagesize=A4)
		w, h = A4
		
		# ========== タイトル ==========
		c.setFont(font, 14)
		c.drawCentredString(w/2, h - 40, '制動装置構造強度計算書')
		c.setFont(font, 9)
		c.drawCentredString(w/2, h - 55, '（ブレーキドラム内圧強度計算）')
		
		y = h - 85
		
		# ========== セクション：入力条件 ==========
		c.setFont(font, 11)
		c.drawString(50, y, '【入力条件】'); y -= 18
		c.setFont(font, 10)
		c.drawString(70, y, f"(a) ブレーキドラム"); y -= 15
		c.drawString(90, y, f"材質: SC25相当"); y -= 12
		c.drawString(90, y, f"内径 ri = {self.last['r_inner']:.1f} mm"); y -= 12
		c.drawString(90, y, f"外径 ro = {self.last['r_outer']:.1f} mm"); y -= 12
		c.drawString(90, y, f"幅 b = {self.last['width']:.1f} mm"); y -= 12
		c.drawString(90, y, f"引張り強さ σb = 250N/mm²"); y -= 12
		c.drawString(70, y, f"(b) 最大ブレーキ内圧: P = {self.last['pressure_mpa']:.3f} MPa"); y -= 18
		
		# ========== 図の描画 ==========
		import math
		cx, cy = w/2 - 100, y - 80  # 図の中心
		outer_r = 35
		inner_r = 24
		
		# 外径円
		c.setStrokeColorRGB(0, 0, 0)
		c.setLineWidth(2)
		c.setFillColorRGB(0.78, 0.86, 0.98)
		c.circle(cx, cy, outer_r, fill=True, stroke=True)
		
		# 内径円
		c.setFillColorRGB(1, 1, 1)
		c.circle(cx, cy, inner_r, fill=True, stroke=True)
		
		# 内圧矢印（4方向）
		c.setStrokeColorRGB(1, 0, 0)
		c.setLineWidth(1.5)
		arrow_len = 10
		for angle in [0, 90, 180, 270]:
			rad = math.radians(angle)
			start_x = cx + inner_r * math.cos(rad)
			start_y = cy + inner_r * math.sin(rad)
			end_x = cx + (inner_r + arrow_len) * math.cos(rad)
			end_y = cy + (inner_r + arrow_len) * math.sin(rad)
			c.line(start_x, start_y, end_x, end_y)
		
		# 図ラベル
		c.setFont(font, 8)
		c.setFillColorRGB(0, 0, 0)
		c.drawString(cx - 30, cy + outer_r + 5, f"ro={self.last['r_outer']:.0f}")
		c.drawString(cx - 30, cy - 8, f"ri={self.last['r_inner']:.0f}")
		
		y = cy - outer_r - 35
		
		# ========== セクション：計算式と結果 ==========
		c.setFont(font, 11)
		c.drawString(50, y, '【計算式と計算結果】'); y -= 18
		c.setFont(font, 9)
		
		# 径比計算
		c.drawString(70, y, f"◆ 径比: n = ro / ri = {self.last['r_outer']:.1f} / {self.last['r_inner']:.1f} = {self.last['k_diameter_ratio']:.4f}"); y -= 12
		
		# Hoop応力計算
		c.drawString(70, y, f"◆ Hoop応力（Lamé理論）"); y -= 12
		c.drawString(90, y, f"σθ = P × (n² + 1) / (n² - 1)"); y -= 11
		c.drawString(90, y, f"   = {self.last['pressure_mpa']:.3f} × ({self.last['k_diameter_ratio']:.4f}² + 1) / ({self.last['k_diameter_ratio']:.4f}² - 1)"); y -= 11
		c.drawString(90, y, f"   = {self.last['sigma_hoop_inner']:.2f} N/mm²（内面）"); y -= 12
		
		# 等価応力
		c.drawString(70, y, f"◆ 等価応力（von Mises）"); y -= 12
		c.drawString(90, y, f"σeq = σθ = {self.last['equivalent_stress']:.2f} N/mm²"); y -= 18
		
		# ========== セクション：材料強度 ==========
		c.setFont(font, 11)
		c.drawString(50, y, '【材料強度】'); y -= 18
		c.setFont(font, 10)
		c.drawString(70, y, f"材質: SC25相当"); y -= 12
		c.drawString(70, y, f"引張強さ σb = {self.last['material_tensile_strength']:.1f} N/mm²"); y -= 12
		c.drawString(70, y, f"降伏点 σy = {self.last['material_yield_strength']:.1f} N/mm²"); y -= 12
		c.drawString(70, y, f"せん断強さ τ = {self.last['material_shear_strength']:.1f} N/mm²"); y -= 18
		
		# ========== セクション：安全率 ==========
		c.setFont(font, 11)
		c.drawString(50, y, f"【安全率】（基準: >= {self.last['min_safety_required']:.1f}倍）"); y -= 18
		c.setFont(font, 10)
		c.drawString(70, y, f"◆ 引張に対して"); y -= 12
		c.drawString(90, y, f"f = σb / σeq = {self.last['material_tensile_strength']:.1f} / {self.last['equivalent_stress']:.2f} = {self.last['safety_factor_tensile']:.2f}"); y -= 12
		status_t = '合格' if self.last['ok_tensile'] else '不合格'
		c.drawString(90, y, f"  ⇒ {status_t} ({self.last['safety_factor_tensile']:.2f} >= {self.last['min_safety_required']:.1f})"); y -= 15
		
		c.drawString(70, y, f"◆ 降伏に対して"); y -= 12
		c.drawString(90, y, f"f = σy / σeq = {self.last['material_yield_strength']:.1f} / {self.last['equivalent_stress']:.2f} = {self.last['safety_factor_yield']:.2f}"); y -= 12
		status_y = '合格' if self.last['ok_yield'] else '不合格'
		c.drawString(90, y, f"  ⇒ {status_y} ({self.last['safety_factor_yield']:.2f} >= {self.last['min_safety_required']:.1f})"); y -= 15
		
		c.drawString(70, y, f"◆ せん断に対して"); y -= 12
		c.drawString(90, y, f"f = τ / (σeq/2) = {self.last['material_shear_strength']:.1f} / {self.last['equivalent_stress']/2:.2f} = {self.last['safety_factor_shear']:.2f}"); y -= 12
		status_s = '合格' if self.last['ok_shear'] else '不合格'
		c.drawString(90, y, f"  ⇒ {status_s} ({self.last['safety_factor_shear']:.2f} >= {self.last['min_safety_required']:.1f})"); y -= 18
		
		# ========== 総合判定 ==========
		c.setFont(font, 12)
		judge = '合格 ✓ OK' if self.last['ok_overall'] else '不合格 ✗ NG'

		
		c.save()
	
	def get_state(self):
		return {
			'r_inner': self.r_inner.GetValue(),
			'r_outer': self.r_outer.GetValue(),
			'width': self.width.GetValue(),
			'pressure': self.pressure.GetValue(),
			'tensile': self.tensile.GetValue(),
			'yield_pt': self.yield_pt.GetValue(),
			'shear': self.shear.GetValue(),
		}
	
	def set_state(self, state):
		if not state:
			return
		if 'r_inner' in state:
			self.r_inner.SetValue(state['r_inner'])
		if 'r_outer' in state:
			self.r_outer.SetValue(state['r_outer'])
		if 'width' in state:
			self.width.SetValue(state['width'])
		if 'pressure' in state:
			self.pressure.SetValue(state['pressure'])
		if 'tensile' in state:
			self.tensile.SetValue(state['tensile'])
		if 'yield_pt' in state:
			self.yield_pt.SetValue(state['yield_pt'])
		if 'shear' in state:
			self.shear.SetValue(state['shear'])
	
	def export_to_path(self, path):
		"""プロジェクト保存時の個別PDF出力"""
		if self.last:
			self._export_pdf(path)

class TowingSpecPanel(wx.Panel):
	"""牽引車の諸元表を作成するパネル"""
	def __init__(self, parent):
		super().__init__(parent)
		self.last = None
		v = wx.BoxSizer(wx.VERTICAL)

		# タイトル
		t = wx.StaticText(self, label='牽引車 諸元')
		f = t.GetFont(); f.PointSize += 2; f = f.Bold(); t.SetFont(f)
		v.Add(t, 0, wx.ALL, 6)

		# 入力フォーム
		grid = wx.FlexGridSizer(0, 4, 6, 8)

		# 車両基本
		self.maker = self._add(grid, 'メーカー', '', '')
		self.model = self._add(grid, '車名・型式', '', '')
		self.vin = self._add(grid, '車台番号(任意)', '', '')
		self.reg_no = self._add(grid, '登録番号(任意)', '', '')

		# 寸法
		self.length = self._add(grid, '全長 [mm]', '', '')
		self.width  = self._add(grid, '全幅 [mm]', '', '')
		self.height = self._add(grid, '全高 [mm]', '', '')
		self.wheelbase = self._add(grid, 'ホイールベース [mm]', '', '')
		self.min_turn = self._add(grid, '最小回転半径 [m]', '', '')
		self.ground_clearance = self._add(grid, '最低地上高 [mm]', '', '')
		self.twf = self._add(grid, '前トレッド [mm]', '', '')
		self.twr = self._add(grid, '後トレッド [mm]', '', '')

		# 重量・能力
		self.curb = self._add(grid, '車両重量 [kg]', '', '')
		self.gvwr = self._add(grid, '車両総重量(許容) [kg]', '', '')
		self.towing_cap = self._add(grid, '牽引能力 [kg]', '', '')
		self.tongue = self._add(grid, '許容垂直荷重(ヒッチ) [kg]', '', '')

		# 動力・駆動
		self.engine = self._add(grid, 'エンジン型式/燃料', '', '')
		self.disp = self._add(grid, '排気量 [cc]', '', '')
		self.power = self._add(grid, '最高出力 [kW]', '', '')
		self.torque = self._add(grid, '最大トルク [N·m]', '', '')
		self.trans = self._add(grid, '変速機(AT/MT/CVT)', '', '')
		self.drive = self._add(grid, '駆動方式(2WD/4WD)', '', '')

		# 足回り・制動
		self.brake = self._add(grid, '制動装置', '', '前後: ディスク/ドラム 等')
		self.tire  = self._add(grid, 'タイヤサイズ', '', '例: 205/60R16')
		self.suspension = self._add(grid, 'サスペンション', '', '例: 前:ストラット/後:トーション, コイルスプリング')

		# ヒッチ装備
		self.hitch_type = self._add(grid, 'ヒッチ種類', '', '50mmボール 等')
		self.connector = self._add(grid, '電気コネクタ', '', '7極/13極 等')
		self.safety_chain_point = self._add(grid, 'セーフティチェーン取付', '', '有/無・取付位置')

		grid.AddGrowableCol(1, 1)
		grid.AddGrowableCol(3, 1)
		box = wx.StaticBoxSizer(wx.StaticBox(self, label='入力'), wx.VERTICAL)
		box.Add(grid, 0, wx.EXPAND | wx.ALL, 6)
		v.Add(box, 0, wx.EXPAND | wx.ALL, 6)

		# ボタン列
		row = wx.BoxSizer(wx.HORIZONTAL)
		btn_preview = wx.Button(self, label='プレビュー')
		btn_pdf     = wx.Button(self, label='PDF出力')
		row.Add(btn_preview, 0, wx.RIGHT, 8)
		row.Add(btn_pdf, 0)
		v.Add(row, 0, wx.ALIGN_CENTER | wx.ALL, 6)

		# プレビュー
		self.preview = wx.TextCtrl(self, style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_WORDWRAP)
		v.Add(self.preview, 1, wx.EXPAND | wx.ALL, 6)

		btn_preview.Bind(wx.EVT_BUTTON, lambda e: (self.on_preview(), e.Skip()))
		btn_pdf.Bind(wx.EVT_BUTTON, lambda e: (self.on_export_pdf(), e.Skip()))

		self.SetSizer(v)

	def _add(self, sizer, label, default='', hint=''):
		ctrl = wx.TextCtrl(self, value=default)
		if hint:
			ctrl.SetHint(hint)
		sizer.Add(wx.StaticText(self, label=label), 0, wx.ALIGN_CENTER_VERTICAL)
		sizer.Add(ctrl, 0, wx.EXPAND)
		return ctrl

	def collect(self) -> dict:
		return {
			'maker': self.maker.GetValue(),
			'model': self.model.GetValue(),
			'vin': self.vin.GetValue(),
			'reg_no': self.reg_no.GetValue(),
			'length': self.length.GetValue(),
			'width': self.width.GetValue(),
			'height': self.height.GetValue(),
			'wheelbase': self.wheelbase.GetValue(),
			'min_turn_radius': self.min_turn.GetValue(),
			'ground_clearance': self.ground_clearance.GetValue(),
			'twf': self.twf.GetValue(),
			'twr': self.twr.GetValue(),
			'curb': self.curb.GetValue(),
			'gvwr': self.gvwr.GetValue(),
			'towing_cap': self.towing_cap.GetValue(),
			'tongue': self.tongue.GetValue(),
			'engine': self.engine.GetValue(),
			'disp': self.disp.GetValue(),
			'power': self.power.GetValue(),
			'torque': self.torque.GetValue(),
			'trans': self.trans.GetValue(),
			'drive': self.drive.GetValue(),
			'brake': self.brake.GetValue(),
			'tire': self.tire.GetValue(),
			'suspension': self.suspension.GetValue(),
			'hitch_type': self.hitch_type.GetValue(),
			'connector': self.connector.GetValue(),
			'safety_chain_point': self.safety_chain_point.GetValue(),
		}

	def on_preview(self):
		data = self.collect()
		lines = []
		lines.append('【車両】')
		lines.append(f"  メーカー: {data['maker']}")
		lines.append(f"  車名・型式: {data['model']}")
		if data['vin']: lines.append(f"  車台番号: {data['vin']}")
		if data['reg_no']: lines.append(f"  登録番号: {data['reg_no']}")
		lines.append('')
		lines.append('【寸法】')
		lines.append(f"  全長×全幅×全高: {data['length']} × {data['width']} × {data['height']} mm")
		lines.append(f"  ホイールベース: {data['wheelbase']} mm")
		lines.append(f"  最小回転半径: {data['min_turn_radius']} m")
		lines.append(f"  最低地上高: {data['ground_clearance']} mm")
		lines.append(f"  前後トレッド: {data['twf']} / {data['twr']} mm")
		lines.append('')
		lines.append('【重量・能力】')
		lines.append(f"  車両重量: {data['curb']} kg  /  総重量(許容): {data['gvwr']} kg")
		lines.append(f"  牽引能力: {data['towing_cap']} kg  /  許容垂直荷重: {data['tongue']} kg")
		lines.append('')
		lines.append('【動力・駆動】')
		lines.append(f"  エンジン/燃料: {data['engine']}  排気量: {data['disp']} cc")
		lines.append(f"  最高出力/最大トルク: {data['power']} kW / {data['torque']} N·m")
		lines.append(f"  変速機: {data['trans']}  駆動方式: {data['drive']}")
		lines.append('')
		lines.append('【足回り】')
		lines.append(f"  制動装置: {data['brake']}  タイヤ: {data['tire']}")
		lines.append(f"  サスペンション: {data['suspension']}")
		lines.append('')
		lines.append('【連結装置】')
		lines.append(f"  ヒッチ: {data['hitch_type']}  電気: {data['connector']}  チェーン: {data['safety_chain_point']}")

		text = '\n'.join(lines)
		self.preview.SetValue(text)
		self.last = data

	def on_export_pdf(self):
		if not _REPORTLAB_AVAILABLE:
			wx.MessageBox('ReportLabが未インストールです。','PDF出力不可',wx.ICON_ERROR)
			return
		if not self.last:
			self.on_preview()
			if not self.last:
				wx.MessageBox('先にプレビューを作成してください。','情報',wx.ICON_INFORMATION)
				return
		with wx.FileDialog(self, 'PDF保存先を選択', wildcard='PDF files (*.pdf)|*.pdf', style=wx.FD_SAVE|wx.FD_OVERWRITE_PROMPT, defaultFile='towing_spec.pdf') as dlg:
			if dlg.ShowModal() != wx.ID_OK:
				return
			path = dlg.GetPath()
		try:
			self.export_to_path(path)
			wx.MessageBox(f'PDF出力完了:\n{path}','完了',wx.ICON_INFORMATION)
		except Exception as e:
			wx.MessageBox(f'PDF出力エラー: {e}','エラー',wx.ICON_ERROR)

	def export_to_path(self, path):
		from reportlab.pdfgen import canvas
		from reportlab.lib.pagesizes import A4
		from reportlab.pdfbase import pdfmetrics
		from reportlab.pdfbase.ttfonts import TTFont
		data = self.last or self.collect()
		# 日本語フォント
		try:
			pdfmetrics.registerFont(TTFont('Japanese', 'C:\\Windows\\Fonts\\meiryo.ttc'))
			font = 'Japanese'
		except Exception:
			font = 'Helvetica'
		c = canvas.Canvas(path, pagesize=A4)
		w, h = A4
		c.setFont(font, 16)
		c.drawString(50, h - 50, '牽引車 諸元表')
		y = h - 90
		c.setFont(font, 10)
		# 車両
		c.drawString(50, y, '【車両】'); y -= 18
		c.drawString(70, y, f"メーカー: {data.get('maker','')}"); y -= 14
		c.drawString(70, y, f"車名・型式: {data.get('model','')}"); y -= 14
		if data.get('vin'): c.drawString(70, y, f"車台番号: {data.get('vin')}"); y -= 14
		if data.get('reg_no'): c.drawString(70, y, f"登録番号: {data.get('reg_no')}"); y -= 18
		# 寸法
		c.drawString(50, y, '【寸法】'); y -= 18
		c.drawString(70, y, f"全長×全幅×全高: {data.get('length','')} × {data.get('width','')} × {data.get('height','')} mm"); y -= 14
		c.drawString(70, y, f"ホイールベース: {data.get('wheelbase','')} mm"); y -= 14
		c.drawString(70, y, f"最小回転半径: {data.get('min_turn_radius','')} m"); y -= 14
		c.drawString(70, y, f"最低地上高: {data.get('ground_clearance','')} mm"); y -= 14
		c.drawString(70, y, f"前後トレッド: {data.get('twf','')} / {data.get('twr','')} mm"); y -= 18
		# 重量・能力
		c.drawString(50, y, '【重量・能力】'); y -= 18
		c.drawString(70, y, f"車両重量: {data.get('curb','')} kg  総重量(許容): {data.get('gvwr','')} kg"); y -= 14
		c.drawString(70, y, f"牽引能力: {data.get('towing_cap','')} kg  許容垂直荷重: {data.get('tongue','')} kg"); y -= 18
		# 動力・駆動
		c.drawString(50, y, '【動力・駆動】'); y -= 18
		c.drawString(70, y, f"エンジン/燃料: {data.get('engine','')}  排気量: {data.get('disp','')} cc"); y -= 14
		c.drawString(70, y, f"最高出力/最大トルク: {data.get('power','')} kW / {data.get('torque','')} N·m"); y -= 14
		c.drawString(70, y, f"変速機: {data.get('trans','')}  駆動方式: {data.get('drive','')}"); y -= 18
		# 足回り
		c.drawString(50, y, '【足回り】'); y -= 18
		c.drawString(70, y, f"制動装置: {data.get('brake','')}  タイヤ: {data.get('tire','')}"); y -= 14
		c.drawString(70, y, f"サスペンション: {data.get('suspension','')}"); y -= 18
		# 連結装置
		c.drawString(50, y, '【連結装置】'); y -= 18
		c.drawString(70, y, f"ヒッチ: {data.get('hitch_type','')}  電気: {data.get('connector','')}  チェーン: {data.get('safety_chain_point','')}"); y -= 18
		c.save()

	def get_state(self):
		return self.collect() | {'preview': self.preview.GetValue()}

	def set_state(self, state):
		self.maker.SetValue(state.get('maker', ''))
		self.model.SetValue(state.get('model', ''))
		self.vin.SetValue(state.get('vin', ''))
		self.reg_no.SetValue(state.get('reg_no', ''))
		self.length.SetValue(state.get('length', ''))
		self.width.SetValue(state.get('width', ''))
		self.height.SetValue(state.get('height', ''))
		self.wheelbase.SetValue(state.get('wheelbase', ''))
		self.min_turn.SetValue(state.get('min_turn_radius', ''))
		self.ground_clearance.SetValue(state.get('ground_clearance', ''))
		self.twf.SetValue(state.get('twf', ''))
		self.twr.SetValue(state.get('twr', ''))
		self.curb.SetValue(state.get('curb', ''))
		self.gvwr.SetValue(state.get('gvwr', ''))
		self.towing_cap.SetValue(state.get('towing_cap', ''))
		self.tongue.SetValue(state.get('tongue', ''))
		self.engine.SetValue(state.get('engine', ''))
		self.disp.SetValue(state.get('disp', ''))
		self.power.SetValue(state.get('power', ''))
		self.torque.SetValue(state.get('torque', ''))
		self.trans.SetValue(state.get('trans', ''))
		self.drive.SetValue(state.get('drive', ''))
		self.brake.SetValue(state.get('brake', ''))
		self.tire.SetValue(state.get('tire', ''))
		self.suspension.SetValue(state.get('suspension', ''))
		self.hitch_type.SetValue(state.get('hitch_type', ''))
		self.connector.SetValue(state.get('connector', ''))
		self.safety_chain_point.SetValue(state.get('safety_chain_point', ''))
		self.preview.SetValue(state.get('preview', ''))

class TwoAxleLeafSpringPanel(wx.Panel):
	"""2軸式板ばねの重量分布計算（前軸/後軸反力）"""
	def __init__(self, parent):
		super().__init__(parent)
		self.last = None
		v = wx.BoxSizer(wx.VERTICAL)
		# タイトル
		t = wx.StaticText(self, label='2軸式板ばね 重量分布計算')
		f = t.GetFont(); f.PointSize += 2; f = f.Bold(); t.SetFont(f)
		v.Add(t, 0, wx.ALL, 6)
		
		# 配置イメージ図を追加
		try:
			diagram_bmp = self._create_layout_diagram()
			if diagram_bmp:
				bmp_ctrl = wx.StaticBitmap(self, bitmap=wx.BitmapBundle.FromBitmap(diagram_bmp))
				v.Add(bmp_ctrl, 0, wx.ALIGN_CENTER | wx.ALL, 8)
		except Exception:
			pass
		
		# 入力レイアウト
		grid = wx.FlexGridSizer(0, 4, 6, 8)
		# 幾何
		self.C_to_front_leaf_front = self._add(grid, '① 連結中心→前板ばね前端 [mm]', '', '800')
		self.C_to_front_leaf_rear  = self._add(grid, '② 連結中心→前板ばね後端 [mm]', '', '1200')
		self.C_to_rear_leaf_front  = self._add(grid, '③ 連結中心→後板ばね前端 [mm]', '', '3000')
		self.C_to_rear_leaf_rear   = self._add(grid, '④ 連結中心→後板ばね後端 [mm]', '', '3400')
		self.bed_start = self._add(grid, '荷台開始位置（連結中心基準）[mm]', '', '1000')
		self.bed_length = self._add(grid, '荷台長さ [mm]', '', '2500')
		# 荷重（フォームに合わせ前後車両重量/積載/装備品）
		self.W_front = self._add(grid, 'トレーラ車両重量 前 [kg]', '', '300')
		self.W_rear  = self._add(grid, 'トレーラ車両重量 後 [kg]', '', '300')
		self.W_payload = self._add(grid, '最大積載量 [kg]', '', '800')
		self.W_equip   = self._add(grid, '装備品重量 [kg]', '', '50')
		self.X_equip   = self._add(grid, '装備品位置（連結中心基準）[mm]', '', '1800')
		grid.AddGrowableCol(1, 1); grid.AddGrowableCol(3, 1)
		box = wx.StaticBoxSizer(wx.StaticBox(self, label='入力'), wx.VERTICAL)
		box.Add(grid, 0, wx.EXPAND | wx.ALL, 6)
		v.Add(box, 0, wx.EXPAND | wx.ALL, 6)
		# ボタン
		row = wx.BoxSizer(wx.HORIZONTAL)
		btn_calc = wx.Button(self, label='計算')
		btn_pdf  = wx.Button(self, label='PDF出力')
		btn_pdf.Enable(False)
		row.Add(btn_calc, 0, wx.RIGHT, 8)
		row.Add(btn_pdf, 0)
		v.Add(row, 0, wx.ALIGN_CENTER | wx.ALL, 6)
		# イベント
		btn_calc.Bind(wx.EVT_BUTTON, lambda e: (self.on_calc(), e.Skip()))
		btn_pdf.Bind(wx.EVT_BUTTON, lambda e: (self.on_export_pdf(), e.Skip()))
		self.btn_pdf = btn_pdf
		self.SetSizer(v)

	def _add(self, sizer, label, default='', hint=''):
		p = wx.TextCtrl(self, value=default, style=wx.TE_RIGHT)
		if hint:
			p.SetHint(hint)
		sizer.Add(wx.StaticText(self, label=label), 0, wx.ALIGN_CENTER_VERTICAL)
		sizer.Add(p, 0, wx.EXPAND)
		return p

	def _create_layout_diagram(self):
		"""配置イメージ図を生成（デフォルト値ベース、GUI表示用）"""
		try:
			w, h = 750, 240
			bmp = wx.Bitmap(w, h)
			dc = wx.MemoryDC(bmp)
			dc.SetBackground(wx.Brush(wx.Colour(255, 255, 255)))
			dc.Clear()
			
			# デフォルト値で描画
			C_ff = 800; C_fr = 1200; C_rf = 3000; C_rr = 3400
			bed_s = 1000; bed_L = 2500
			Xf = (C_ff + C_fr) / 2.0
			Xr = (C_rf + C_rr) / 2.0
			Xp = bed_s + bed_L / 2.0
			
			# スケール設定
			margin = 50
			total_len = max(C_rr, bed_s + bed_L) + 200
			scale = (w - 2 * margin) / total_len
			base_y = h // 2 + 20
			
			def to_x(pos): return int(margin + pos * scale)
			
			# 連結中心（赤丸）
			dc.SetBrush(wx.Brush(wx.Colour(255, 0, 0)))
			dc.SetPen(wx.Pen(wx.Colour(200, 0, 0), 2))
			dc.DrawCircle(to_x(0), base_y, 8)
			dc.SetTextForeground(wx.Colour(200, 0, 0))
			dc.SetFont(wx.Font(9, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD))
			dc.DrawText('連結中心', to_x(0) - 28, base_y - 35)
			
			# 梁（灰色線）
			dc.SetPen(wx.Pen(wx.Colour(80, 80, 80), 3))
			dc.DrawLine(to_x(0), base_y, to_x(total_len - 200), base_y)
			
			# 前後板ばね（青の四角）
			dc.SetBrush(wx.Brush(wx.Colour(100, 150, 255)))
			dc.SetPen(wx.Pen(wx.Colour(50, 100, 200), 2))
			leaf_h = 24
			dc.DrawRectangle(to_x(C_ff), base_y - leaf_h // 2, to_x(C_fr) - to_x(C_ff), leaf_h)
			dc.DrawRectangle(to_x(C_rf), base_y - leaf_h // 2, to_x(C_rr) - to_x(C_rf), leaf_h)
			dc.SetTextForeground(wx.Colour(50, 100, 200))
			dc.SetFont(wx.Font(8, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL))
			dc.DrawText('前板ばね', to_x((C_ff + C_fr) / 2) - 24, base_y - 45)
			dc.DrawText('後板ばね', to_x((C_rf + C_rr) / 2) - 24, base_y - 45)
			
			# 前後軸中心（青三角マーカー）
			dc.SetBrush(wx.Brush(wx.Colour(0, 100, 200)))
			for xc in [Xf, Xr]:
				sx = to_x(xc)
				pts = [wx.Point(sx - 10, base_y + 14), wx.Point(sx, base_y + 28), wx.Point(sx + 10, base_y + 14)]
				dc.DrawPolygon(pts)
			dc.DrawText('前軸中心', to_x(Xf) - 24, base_y + 32)
			dc.DrawText('後軸中心', to_x(Xr) - 24, base_y + 32)
			
			# 荷台範囲（緑の半透明矩形）
			dc.SetBrush(wx.Brush(wx.Colour(150, 255, 150, 128)))
			dc.SetPen(wx.Pen(wx.Colour(0, 180, 0), 1))
			bed_top = base_y - 70
			dc.DrawRectangle(to_x(bed_s), bed_top, to_x(bed_s + bed_L) - to_x(bed_s), 50)
			dc.SetTextForeground(wx.Colour(0, 150, 0))
			dc.SetFont(wx.Font(9, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD))
			dc.DrawText('荷台', to_x(bed_s + bed_L / 2) - 15, bed_top - 18)
			
			# 最大積載中心（緑矢印）
			dc.SetPen(wx.Pen(wx.Colour(0, 180, 0), 2))
			dc.SetBrush(wx.Brush(wx.Colour(0, 180, 0)))
			arr_x = to_x(Xp)
			dc.DrawLine(arr_x, bed_top - 30, arr_x, bed_top - 5)
			dc.DrawPolygon([wx.Point(arr_x - 6, bed_top - 10), wx.Point(arr_x + 6, bed_top - 10), wx.Point(arr_x, bed_top - 5)])
			dc.SetTextForeground(wx.Colour(0, 150, 0))
			dc.SetFont(wx.Font(8, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL))
			dc.DrawText('積載中心', arr_x - 24, bed_top - 42)
			
			# 凡例
			dc.SetFont(wx.Font(8, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL))
			dc.SetTextForeground(wx.Colour(0, 0, 0))
			dc.DrawText('※ 入力値はデフォルト例。各位置は連結中心基準 [mm]。', 10, h - 22)
			
			dc.SelectObject(wx.NullBitmap)
			return bmp
		except Exception:
			return None

	def _compute_support_centers(self):
		# 前後板ばね中心（端の平均）
		Xf = (float(self.C_to_front_leaf_front.GetValue()) + float(self.C_to_front_leaf_rear.GetValue())) / 2.0
		Xr = (float(self.C_to_rear_leaf_front.GetValue()) + float(self.C_to_rear_leaf_rear.GetValue())) / 2.0
		if Xr <= Xf:
			raise ValueError('後軸中心が前軸中心以下です。入力を確認してください。')
		return Xf, Xr

	def on_calc(self):
		try:
			Xf, Xr = self._compute_support_centers()
			bed_s = float(self.bed_start.GetValue()); bed_L = float(self.bed_length.GetValue())
			# 荷重定義: 複数点荷重（位置は連結中心基準）
			Wf = float(self.W_front.GetValue()); Wr = float(self.W_rear.GetValue())
			Wp = float(self.W_payload.GetValue()); We = float(self.W_equip.GetValue()); Xe = float(self.X_equip.GetValue())
			loads = []
			# 車両重量 前/後: それぞれ前/後軸中心に作用（簡易モデル）
			loads.append((Wf, Xf))
			loads.append((Wr, Xr))
			# 最大積載量: 荷台中央に作用
			Xp = bed_s + bed_L/2.0
			loads.append((Wp, Xp))
			# 装備品: 指定位置
			loads.append((We, Xe))
			# 2支点反力（静的釣り合い）
			den = (Xr - Xf)
			if den <= 0:
				raise ValueError('支点距離が不正です。')
			Rf = sum(W * (Xr - x) / den for (W, x) in loads)
			Rr = sum(W * (x - Xf) / den for (W, x) in loads)
			Wtot = sum(W for (W, _) in loads)
			self.last = dict(Xf=Xf, Xr=Xr, bed_s=bed_s, bed_L=bed_L, Xp=Xp, Xe=Xe,
				Wf=Wf, Wr=Wr, Wp=Wp, We=We, Wtot=Wtot, Rf=Rf, Rr=Rr)
			# 結果表示
			text = '\n'.join([
				'◆ 2軸式板ばね 重量分布計算結果 ◆',
				f"支点(前軸) Xf = {Xf:.1f} mm, 支点(後軸) Xr = {Xr:.1f} mm",
				f"荷台中央 Xp = {Xp:.1f} mm, 装備品位置 Xe = {Xe:.1f} mm",
				'— 入力荷重 —',
				f"前重量 Wf = {Wf:.1f} kg @ Xf", f"後重量 Wr = {Wr:.1f} kg @ Xr",
				f"最大積載量 Wp = {Wp:.1f} kg @ Xp", f"装備品 We = {We:.1f} kg @ Xe",
				'— 反力 —',
				f"前軸反力 Rf = {Rf:.1f} kg", f"後軸反力 Rr = {Rr:.1f} kg",
				f"総重量 Wtot = {Wtot:.1f} kg",
			])
			show_result('2軸式板ばね 重量分布', text)
			self.btn_pdf.Enable(True)
		except ValueError:
			wx.MessageBox('数値入力を確認してください。', '入力エラー', wx.ICON_ERROR)
		except Exception as e:
			wx.MessageBox(f'計算エラー: {e}', 'エラー', wx.ICON_ERROR)

	def _create_layout_diagram_png(self, v):
		"""計算結果ベースで配置図をPNG生成してパスを返す"""
		try:
			w, h = 700, 220
			bmp = wx.Bitmap(w, h)
			dc = wx.MemoryDC(bmp)
			dc.SetBackground(wx.Brush(wx.Colour(255, 255, 255)))
			dc.Clear()
			
			# 実測値
			C_ff = float(self.C_to_front_leaf_front.GetValue())
			C_fr = float(self.C_to_front_leaf_rear.GetValue())
			C_rf = float(self.C_to_rear_leaf_front.GetValue())
			C_rr = float(self.C_to_rear_leaf_rear.GetValue())
			bed_s = v['bed_s']; bed_L = v['bed_L']
			Xf = v['Xf']; Xr = v['Xr']; Xp = v['Xp']; Xe = v['Xe']
			
			margin = 50
			total_len = max(C_rr, bed_s + bed_L, Xe) + 200
			scale = (w - 2 * margin) / total_len
			base_y = h // 2 + 20
			
			def to_x(pos): return int(margin + pos * scale)
			
			# 連結中心
			dc.SetBrush(wx.Brush(wx.Colour(255, 0, 0)))
			dc.SetPen(wx.Pen(wx.Colour(200, 0, 0), 2))
			dc.DrawCircle(to_x(0), base_y, 7)
			dc.SetTextForeground(wx.Colour(200, 0, 0))
			dc.SetFont(wx.Font(8, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD))
			dc.DrawText('C', to_x(0) - 5, base_y - 30)
			
			# 梁
			dc.SetPen(wx.Pen(wx.Colour(80, 80, 80), 3))
			dc.DrawLine(to_x(0), base_y, to_x(total_len - 200), base_y)
			
			# 前後板ばね（青）
			dc.SetBrush(wx.Brush(wx.Colour(100, 150, 255)))
			dc.SetPen(wx.Pen(wx.Colour(50, 100, 200), 2))
			leaf_h = 20
			dc.DrawRectangle(to_x(C_ff), base_y - leaf_h // 2, to_x(C_fr) - to_x(C_ff), leaf_h)
			dc.DrawRectangle(to_x(C_rf), base_y - leaf_h // 2, to_x(C_rr) - to_x(C_rf), leaf_h)
			dc.SetTextForeground(wx.Colour(50, 100, 200))
			dc.SetFont(wx.Font(7, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL))
			dc.DrawText('前葉', to_x((C_ff + C_fr) / 2) - 12, base_y - 38)
			dc.DrawText('後葉', to_x((C_rf + C_rr) / 2) - 12, base_y - 38)
			
			# 前後軸中心（三角）
			dc.SetBrush(wx.Brush(wx.Colour(0, 100, 200)))
			for xc, lbl in [(Xf, '前軸'), (Xr, '後軸')]:
				sx = to_x(xc)
				pts = [wx.Point(sx - 8, base_y + 12), wx.Point(sx, base_y + 24), wx.Point(sx + 8, base_y + 12)]
				dc.DrawPolygon(pts)
				dc.DrawText(lbl, sx - 12, base_y + 28)
			
			# 荷台（緑矩形）
			dc.SetBrush(wx.Brush(wx.Colour(150, 255, 150, 100)))
			dc.SetPen(wx.Pen(wx.Colour(0, 180, 0), 1))
			bed_top = base_y - 65
			dc.DrawRectangle(to_x(bed_s), bed_top, to_x(bed_s + bed_L) - to_x(bed_s), 45)
			dc.SetTextForeground(wx.Colour(0, 150, 0))
			dc.SetFont(wx.Font(8, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD))
			dc.DrawText('荷台', to_x(bed_s + bed_L / 2) - 12, bed_top - 16)
			
			# 積載中心（緑矢印）
			dc.SetPen(wx.Pen(wx.Colour(0, 180, 0), 2))
			dc.SetBrush(wx.Brush(wx.Colour(0, 180, 0)))
			arr_x = to_x(Xp)
			dc.DrawLine(arr_x, bed_top - 26, arr_x, bed_top - 3)
			dc.DrawPolygon([wx.Point(arr_x - 5, bed_top - 8), wx.Point(arr_x + 5, bed_top - 8), wx.Point(arr_x, bed_top - 3)])
			dc.SetTextForeground(wx.Colour(0, 150, 0))
			dc.SetFont(wx.Font(7, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL))
			dc.DrawText('積載', arr_x - 12, bed_top - 36)
			
			# 装備品位置（オレンジ矢印）
			if Xe > 0:
				dc.SetPen(wx.Pen(wx.Colour(255, 140, 0), 2))
				dc.SetBrush(wx.Brush(wx.Colour(255, 140, 0)))
				ex = to_x(Xe)
				dc.DrawLine(ex, base_y - 50, ex, base_y - 5)
				dc.DrawPolygon([wx.Point(ex - 5, base_y - 10), wx.Point(ex + 5, base_y - 10), wx.Point(ex, base_y - 5)])
				dc.SetTextForeground(wx.Colour(255, 100, 0))
				dc.DrawText('装備', ex - 12, base_y - 60)
			
			dc.SelectObject(wx.NullBitmap)
			fd, path = tempfile.mkstemp(suffix='.png', prefix='leaf_layout_')
			os.close(fd)
			bmp.SaveFile(path, wx.BITMAP_TYPE_PNG)
			return path
		except Exception:
			return ''

	def on_export_pdf(self):
		if self.last is None:
			wx.MessageBox('先に計算を実行してください。', 'PDF出力', wx.ICON_INFORMATION); return
		if not _REPORTLAB_AVAILABLE:
			wx.MessageBox('ReportLabが未インストールです。', 'PDF出力不可', wx.ICON_ERROR); return
		with wx.FileDialog(self, message='PDF保存', wildcard='PDF files (*.pdf)|*.pdf', style=wx.FD_SAVE|wx.FD_OVERWRITE_PROMPT, defaultFile='2軸式板ばね重量分布計算書.pdf') as dlg:
			if dlg.ShowModal() != wx.ID_OK: return
			path = dlg.GetPath()
		try:
			c = _pdf_canvas.Canvas(path, pagesize=_A4)
			W, H = _A4
			font = 'Helvetica'
			for f in ['C:/Windows/Fonts/msgothic.ttc', 'C:/Windows/Fonts/meiryo.ttc', 'C:/Windows/Fonts/yugothic.ttf', 'ipaexg.ttf','ipaexm.ttf','fonts/ipaexg.ttf','fonts/ipaexm.ttf']:
				if os.path.exists(f):
					try:
						_pdfmetrics.registerFont(_TTFont('JPLeaf', f)); font='JPLeaf'; break
					except Exception: pass
			v = self.last
			left=40; bottom=50; top=40
			y=H-top
			c.setFont(font,14); c.drawString(left,y,'2軸式板ばね重量分布計算書'); y-=22; c.setFont(font,9)
			
			# 配置図をPDFに挿入
			layout_png = self._create_layout_diagram_png(v)
			if layout_png:
				try:
					img_w = 650; img_h = 220
					c.drawImage(layout_png, left - 20, y - img_h, width=img_w, height=img_h, preserveAspectRatio=True, mask='auto')
					y -= img_h + 12
				except Exception:
					pass
			
			# 入力・結果テーブル
			def table(x,y,cw,rh,rows):
				Wtot=sum(cw); Ht=rh*len(rows); c.rect(x,y-Ht,Wtot,Ht)
				for i in range(1,len(rows)): c.line(x,y-rh*i,x+Wtot,y-rh*i)
				cx=x
				for wcol in cw[:-1]: cx+=wcol; c.line(cx,y,cx,y-Ht)
				for r,row in enumerate(rows):
					cy=y-rh*(r+1)+5; cx=x+4
					for j,cell in enumerate(row): c.drawString(cx,cy,str(cell)); cx+=cw[j]
				return y-Ht-10
			cw=[120,120,120]
			y=table(left,y,[180,120,120],18,[
				['項目','値','単位'],
				['材質 名称', v.get('material',''), ''],
				['支点(前軸) Xf', f"{v['Xf']:.1f}", 'mm'],
				['支点(後軸) Xr', f"{v['Xr']:.1f}", 'mm'],
				['荷台開始', f"{v['bed_s']:.1f}", 'mm'],
				['荷台長さ', f"{v['bed_L']:.1f}", 'mm'],
				['荷台中央 Xp', f"{v['Xp']:.1f}", 'mm'],
				['装備品位置 Xe', f"{v['Xe']:.1f}", 'mm'],
			])
			y=table(left,y,[180,120,120],18,[
				['荷重','値','単位'],
				['前重量 Wf', f"{v['Wf']:.1f}", 'kg'],
				['後重量 Wr', f"{v['Wr']:.1f}", 'kg'],
				['最大積載量 Wp', f"{v['Wp']:.1f}", 'kg'],
				['装備品 We', f"{v['We']:.1f}", 'kg'],
				['総重量 Wtot', f"{v['Wtot']:.1f}", 'kg'],
			])
			y=table(left,y,[140,120,120],16,[
				['反力','値','単位'],
				['前軸反力 Rf', f"{v['Rf']:.1f}", 'kg'],
				['後軸反力 Rr', f"{v['Rr']:.1f}", 'kg'],
			])
			# 式
			c.setFont(font,10); c.drawString(left,y-8,'計算式'); c.setFont(font,8); y-=22
			c.drawString(left,y,'Rf = Σ(Wi × (Xr − xi)) / (Xr − Xf)'); y-=12
			c.drawString(left,y,'Rr = Σ(Wi × (xi − Xf)) / (Xr − Xf)'); y-=12
			c.drawString(left,y,'荷台中央 Xp = 荷台開始 + 荷台長さ/2'); y-=12
			# 根拠・考え方
			y -= 6
			c.setFont(font,10); c.drawString(left, y, '根拠・考え方'); y -= 14; c.setFont(font,8)
			c.drawString(left+5, y, '・2支点梁の静的釣り合いより、ΣWi = Rf + Rr, Σモーメント=0。'); y -= 12
			c.drawString(left+5, y, '・これより Rf = Σ[Wi×(Xr−xi)]/(Xr−Xf), Rr = Σ[Wi×(xi−Xf)]/(Xr−Xf)。'); y -= 12
			c.drawString(left+5, y, '・荷重モデル: 前/後の車両重量は各軸中心、最大積載は荷台中央、装備品は指定位置に集中荷重。'); y -= 12
			c.drawString(left+5, y, '・位置は連結中心基準の mm、荷重は kg（重量換算の簡易モデル）で評価しています。'); y -= 12
			c.save(); _open_saved_pdf(path); wx.MessageBox('PDFを保存しました。','完了',wx.ICON_INFORMATION)
		except Exception as e:
			wx.MessageBox(f'PDF出力中エラー: {e}','エラー',wx.ICON_ERROR)

	def get_state(self):
		return {
			'C_to_front_leaf_front': self.C_to_front_leaf_front.GetValue(),
			'C_to_front_leaf_rear': self.C_to_front_leaf_rear.GetValue(),
			'C_to_rear_leaf_front': self.C_to_rear_leaf_front.GetValue(),
			'C_to_rear_leaf_rear': self.C_to_rear_leaf_rear.GetValue(),
			'bed_start': self.bed_start.GetValue(),
			'bed_length': self.bed_length.GetValue(),
			'W_front': self.W_front.GetValue(),
			'W_rear': self.W_rear.GetValue(),
			'W_payload': self.W_payload.GetValue(),
			'W_equip': self.W_equip.GetValue(),
			'X_equip': self.X_equip.GetValue(),
			'last': self.last
		}

	def set_state(self, state):
		if not state:
			return
		if 'C_to_front_leaf_front' in state:
			self.C_to_front_leaf_front.SetValue(str(state['C_to_front_leaf_front']))
		if 'C_to_front_leaf_rear' in state:
			self.C_to_front_leaf_rear.SetValue(str(state['C_to_front_leaf_rear']))
		if 'C_to_rear_leaf_front' in state:
			self.C_to_rear_leaf_front.SetValue(str(state['C_to_rear_leaf_front']))
		if 'C_to_rear_leaf_rear' in state:
			self.C_to_rear_leaf_rear.SetValue(str(state['C_to_rear_leaf_rear']))
		if 'bed_start' in state:
			self.bed_start.SetValue(str(state['bed_start']))
		if 'bed_length' in state:
			self.bed_length.SetValue(str(state['bed_length']))
		if 'W_front' in state:
			self.W_front.SetValue(str(state['W_front']))
		if 'W_rear' in state:
			self.W_rear.SetValue(str(state['W_rear']))
		if 'W_payload' in state:
			self.W_payload.SetValue(str(state['W_payload']))
		if 'W_equip' in state:
			self.W_equip.SetValue(str(state['W_equip']))
		if 'X_equip' in state:
			self.X_equip.SetValue(str(state['X_equip']))
		if 'last' in state:
			self.last = state['last']

	def export_to_path(self, path):
		if self.last is None or not _REPORTLAB_AVAILABLE:
			return
		try:
			c=_pdf_canvas.Canvas(path,pagesize=_A4)
			W,H=_A4
			font='Helvetica'
			for f in ['C:/Windows/Fonts/msgothic.ttc', 'C:/Windows/Fonts/meiryo.ttc', 'C:/Windows/Fonts/yugothic.ttf', 'ipaexg.ttf','ipaexm.ttf','fonts/ipaexg.ttf','fonts/ipaexm.ttf']:
				if os.path.exists(f):
					try:
						_pdfmetrics.registerFont(_TTFont('JPSpring',f)); font='JPSpring'; break
					except Exception:
						pass
			v = self.last
			left=40; bottom=50; top=40
			y=H-top
			c.setFont(font,14); c.drawString(left,y,'2軸式板ばね重量分布計算書'); y-=22; c.setFont(font,9)
			layout_png = self._create_layout_diagram_png(v)
			if layout_png:
				try:
					img_w = 650; img_h = 220
					c.drawImage(layout_png, left - 20, y - img_h, width=img_w, height=img_h, preserveAspectRatio=True, mask='auto')
					y -= img_h + 12
				except Exception:
					pass
			def table(x,y,cw,rh,rows):
				Wtot=sum(cw); Ht=rh*len(rows); c.rect(x,y-Ht,Wtot,Ht)
				for i in range(1,len(rows)): c.line(x,y-rh*i,x+Wtot,y-rh*i)
				cx=x
				for wcol in cw[:-1]: cx+=wcol; c.line(cx,y,cx,y-Ht)
				for r,row in enumerate(rows):
					cy=y-rh*(r+1)+5; cx=x+4
					for j,cell in enumerate(row): c.drawString(cx,cy,str(cell)); cx+=cw[j]
				return y-Ht-10
			cw=[120,120,120]
			y=table(left,y,[180,120,120],18,[
				['項目','値','単位'],
				['材質 名称', v.get('material',''), ''],
				['支点(前軸) Xf', f"{v['Xf']:.1f}", 'mm'],
				['支点(後軸) Xr', f"{v['Xr']:.1f}", 'mm'],
				['荷台開始', f"{v['bed_s']:.1f}", 'mm'],
				['荷台長さ', f"{v['bed_L']:.1f}", 'mm'],
				['荷台中央 Xp', f"{v['Xp']:.1f}", 'mm'],
				['装備品位置 Xe', f"{v['Xe']:.1f}", 'mm'],
			])
			y=table(left,y,[180,120,120],18,[
				['荷重','値','単位'],
				['前重量 Wf', f"{v['Wf']:.1f}", 'kg'],
				['後重量 Wr', f"{v['Wr']:.1f}", 'kg'],
				['最大積載量 Wp', f"{v['Wp']:.1f}", 'kg'],
				['装備品 We', f"{v['We']:.1f}", 'kg'],
				['総重量 Wtot', f"{v['Wtot']:.1f}", 'kg'],
			])
			y=table(left,y,[140,120,120],16,[
				['反力','値','単位'],
				['前軸反力 Rf', f"{v['Rf']:.1f}", 'kg'],
				['後軸反力 Rr', f"{v['Rr']:.1f}", 'kg'],
			])
			c.setFont(font,10); c.drawString(left,y-8,'計算式'); c.setFont(font,8); y-=22
			c.drawString(left,y,'Rf = Σ(Wi × (Xr − xi)) / (Xr − Xf)'); y-=12
			c.drawString(left,y,'Rr = Σ(Wi × (xi − Xf)) / (Xr − Xf)'); y-=12
			c.drawString(left,y,'荷台中央 Xp = 荷台開始 + 荷台長さ/2'); y-=12
			# 根拠・考え方
			y -= 6
			c.setFont(font,10); c.drawString(left, y, '根拠・考え方'); y -= 14; c.setFont(font,8)
			c.drawString(left+5, y, '・2支点梁の静的釣り合いより、ΣWi = Rf + Rr, Σモーメント=0。'); y -= 12
			c.drawString(left+5, y, '・これより Rf = Σ[Wi×(Xr−xi)]/(Xr−Xf), Rr = Σ[Wi×(xi−Xf)]/(Xr−Xf)。'); y -= 12
			c.drawString(left+5, y, '・荷重モデル: 前/後の車両重量は各軸中心、最大積載は荷台中央、装備品は指定位置に集中荷重。'); y -= 12
			c.drawString(left+5, y, '・位置は連結中心基準の mm、荷重は kg（重量換算の簡易モデル）で評価しています。'); y -= 12
			c.save()
		except Exception:
			pass


class LeafSpringCushionStrengthPanel(wx.Panel):
	"""緩衝装置強度計算書"""

	def __init__(self, parent):
		super().__init__(parent)
		self.last: dict | None = None

		main = wx.BoxSizer(wx.VERTICAL)
		t = wx.StaticText(self, label='緩衝装置強度')
		f = t.GetFont(); f.PointSize += 2; f = f.Bold(); t.SetFont(f)
		main.Add(t, 0, wx.ALL, 6)

		# 計算概要説明入力エリア
		desc_box = wx.StaticBoxSizer(wx.StaticBox(self, label='計算概要（任意）'), wx.VERTICAL)
		self.description = wx.TextCtrl(self, style=wx.TE_MULTILINE | wx.TE_WORDWRAP)
		self.description.SetHint('計算に関する概要、条件、備考など記入してください（PDF出力時に冒頭に表示されます）')
		desc_box.Add(self.description, 1, wx.EXPAND | wx.ALL, 4)
		main.Add(desc_box, 0, wx.EXPAND | wx.ALL, 6)

		box = wx.StaticBoxSizer(wx.StaticBox(self, label='入力'), wx.VERTICAL)
		grid = wx.FlexGridSizer(0, 4, 6, 8)

		# 重量
		self.WR_total = self._add(grid, '後軸重量 WR [kg]', '', '24830')
		self.Wu_unsprung = self._add(grid, 'ばね下重量 Wu [kg]', '', '3590')
		self.spring_count = self._add(grid, 'ばね本数 [本]', '', '6')
		# 寸法
		self.b_width = self._add(grid, 'ばね幅 b [mm]', '', '90')
		self.t_thickness = self._add(grid, '板厚 t [mm]', '', '13')
		self.n_leaves = self._add(grid, '枚数 n [枚]', '', '8')
		self.l_span = self._add(grid, '有効スパン l [mm]', '', '820')
		self.l1_ubolt = self._add(grid, 'Uボルト間隔 l1 [mm]', '', '200')

		# 材質
		self.material = self._add(grid, '材質', '', 'sup9')
		self.sigma_b = self._add(grid, '引張り強さ σB [N/mm²]', '', '1520')
		self.sigma_y = self._add(grid, '降伏強さ σY [N/mm²]', '', '1370')

		grid.AddGrowableCol(1, 1)
		grid.AddGrowableCol(3, 1)
		box.Add(grid, 0, wx.EXPAND | wx.ALL, 6)
		main.Add(box, 0, wx.EXPAND | wx.ALL, 6)

		row = wx.BoxSizer(wx.HORIZONTAL)
		btn_calc = wx.Button(self, label='計算')
		btn_pdf = wx.Button(self, label='PDF出力')
		btn_pdf.Enable(_REPORTLAB_AVAILABLE)
		if not _REPORTLAB_AVAILABLE:
			btn_pdf.SetToolTip('ReportLab未インストールのためPDF出力は無効です。requirements.txtをインストールしてください。')
		row.Add(btn_calc, 0, wx.RIGHT, 8)
		row.Add(btn_pdf, 0)
		main.Add(row, 0, wx.ALIGN_CENTER | wx.ALL, 6)
		self.btn_pdf = btn_pdf

		btn_calc.Bind(wx.EVT_BUTTON, lambda e: (self.on_calc(), e.Skip()))
		btn_pdf.Bind(wx.EVT_BUTTON, lambda e: (self.on_export_pdf(), e.Skip()))

		self.SetSizer(main)

	def _add(self, sizer, label, default='', hint='') -> wx.TextCtrl:
		p = wx.TextCtrl(self, value=default, style=wx.TE_RIGHT)
		if hint:
			p.SetHint(hint)
		sizer.Add(wx.StaticText(self, label=label), 0, wx.ALIGN_CENTER_VERTICAL)
		sizer.Add(p, 0, wx.EXPAND)
		return p

	def _f(self, ctrl: wx.TextCtrl) -> float:
		v = ctrl.GetValue().strip()
		if v == '':
			raise ValueError('未入力の項目があります。')
		return float(v)

	def on_calc(self):
		"""添付形式の板ばね応力・安全率を算出"""
		try:
			# 添付例に合わせ g=9.8 を採用
			g = 9.8
			WR = self._f(self.WR_total)
			Wu = self._f(self.Wu_unsprung)
			spring_count = int(self._f(self.spring_count))
			b = self._f(self.b_width)
			t = self._f(self.t_thickness)
			n = int(self._f(self.n_leaves))
			l = self._f(self.l_span)
			l1 = self._f(self.l1_ubolt)
			sigma_b = self._f(self.sigma_b)
			sigma_y = self._f(self.sigma_y)

			if spring_count <= 0:
				raise ValueError('ばね本数は1以上で入力してください。')
			if n <= 0:
				raise ValueError('枚数nは1以上で入力してください。')
			if l <= l1:
				raise ValueError('有効スパン l は Uボルト間隔 l1 より大きくしてください。')
			if b <= 0 or t <= 0:
				raise ValueError('ばね幅b/板厚tは正の値で入力してください。')

			Wr = WR - Wu
			if Wr <= 0:
				raise ValueError('ばね上重量 Wr = WR - Wu が0以下です。入力を確認してください。')

			W_per_spring_kg = Wr / float(spring_count)
			# σ = 3*W*(l-l1) / (2*b*t^2*n) * g
			sigma = (3.0 * (W_per_spring_kg * g) * (l - l1)) / (2.0 * b * (t ** 2) * float(n))

			# 添付例の安全率計算（2.5係数）
			k = 2.5
			fb = sigma_b / (k * sigma) if sigma > 0 else 0.0
			fy = sigma_y / (k * sigma) if sigma > 0 else 0.0
			ok_fb = fb >= 1.6
			ok_fy = fy >= 1.3

			self.last = {
				'g': g,
				'WR': WR,
				'Wu': Wu,
				'Wr': Wr,
				'spring_count': spring_count,
				'W_per': W_per_spring_kg,
				'b': b,
				't': t,
				'n': n,
				'l': l,
				'l1': l1,
				'material': self.material.GetValue(),
				'sigma_b': sigma_b,
				'sigma_y': sigma_y,
				'sigma': sigma,
				'k': k,
				'fb': fb,
				'fy': fy,
				'ok_fb': ok_fb,
				'ok_fy': ok_fy,
				'description': self.description.GetValue(),
			}

			text = '\n'.join([
				'《緩衝装置強度計算書》',
				'',
				'○寸法諸元',
				f"後軸重量 WR : {WR:.0f} kg",
				f"ばね下重量 Wu : {Wu:.0f} kg",
				f"ばね上重量 Wr : {Wr:.0f} kg",
				f"ばね1本当たりの重量 W = Wr/{spring_count} : {W_per_spring_kg:.0f} kg",
				f"ばね幅 b : {b:.0f} mm",
				f"板厚 t : {t:.0f} mm",
				f"ばねの枚数 n : {n} 枚",
				f"有効スパン l : {l:.0f} mm",
				f"Uボルト間隔 l1 : {l1:.0f} mm",
				'',
				'○ばね材質',
				f"材質 : {self.material.GetValue()}",
				f"引張り強さ : {sigma_b:.0f} N/mm²",
				f"降伏強さ : {sigma_y:.0f} N/mm²",
				'',
				'○ばね応力 σ [N/mm²]',
				'σ = (3×W×(l−l1)) / (2×b×t²×n) × g',
				f"g = {g:.1f} m/s²",
				f"σ = {sigma:.2f} N/mm²",
				'',
				'○安全率',
				f"破壊安全率 fb = σB / ({k:.1f}×σ) = {fb:.2f}  → {'OK' if ok_fb else 'NG'} (基準 1.6以上)",
				f"降伏安全率 fy = σY / ({k:.1f}×σ) = {fy:.2f}  → {'OK' if ok_fy else 'NG'} (基準 1.3以上)",
			])
			show_result('緩衝装置強度', text)
			self.btn_pdf.Enable(True)
		except ValueError as e:
			wx.MessageBox(str(e), '入力エラー', wx.ICON_ERROR)
		except Exception as e:
			wx.MessageBox(f'計算エラー: {e}', 'エラー', wx.ICON_ERROR)

	def _pdf_font(self):
		font = 'Helvetica'
		for f in [
			'C:/Windows/Fonts/msgothic.ttc',
			'C:/Windows/Fonts/meiryo.ttc',
			'C:/Windows/Fonts/yugothic.ttf',
			'ipaexg.ttf',
			'ipaexm.ttf',
			'fonts/ipaexg.ttf',
			'fonts/ipaexm.ttf',
		]:
			if os.path.exists(f):
				try:
					_pdfmetrics.registerFont(_TTFont('JPCushion', f))
					font = 'JPCushion'
					break
				except Exception:
					pass
		return font

	def on_export_pdf(self):
		if self.last is None:
			wx.MessageBox('先に計算を実行してください。', 'PDF出力', wx.ICON_INFORMATION)
			return
		if not _REPORTLAB_AVAILABLE:
			wx.MessageBox('ReportLabが未インストールです。', 'PDF出力不可', wx.ICON_ERROR)
			return
		with wx.FileDialog(
			self,
			message='PDF保存',
			wildcard='PDF files (*.pdf)|*.pdf',
			style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT,
			defaultFile='緩衝装置強度計算書.pdf',
		) as dlg:
			if dlg.ShowModal() != wx.ID_OK:
				return
			path = dlg.GetPath()
		try:
			self.export_to_path(path)
			_open_saved_pdf(path)
			wx.MessageBox('PDFを保存しました。', '完了', wx.ICON_INFORMATION)
		except Exception as e:
			wx.MessageBox(f'PDF出力中エラー: {e}', 'エラー', wx.ICON_ERROR)

	def export_to_path(self, path):
		if self.last is None or not _REPORTLAB_AVAILABLE:
			return
		v = self.last
		c = _pdf_canvas.Canvas(path, pagesize=_A4)
		W, H = _A4
		font = self._pdf_font()
		left = 40
		y = H - 40

		c.setFont(font, 14)
		c.drawString(left, y, '緩衝装置強度計算書')
		y -= 22
		c.setFont(font, 9)
		#c.drawString(left, y, '※添付例に合わせ g=9.8、係数2.5で評価')
		y -= 18

		# 計算概要説明を表示
		if v.get('description', '').strip():
			c.setFont(font, 10)
			c.drawString(left, y, '【概要】')
			y -= 14
			c.setFont(font, 9)
			# 説明文を複数行で表示
			desc_lines = v['description'].strip().split('\n')
			for line in desc_lines:
				if y < 60:  # ページの余白を考慮
					c.showPage()
					c.setFont(font, 9)
					y = H - 40
				c.drawString(left, y, line)
				y -= 12
			y -= 6

		def table(x, y, col_w, row_h, rows):
			Wtot = sum(col_w)
			Ht = row_h * len(rows)
			c.rect(x, y - Ht, Wtot, Ht)
			for i in range(1, len(rows)):
				c.line(x, y - row_h * i, x + Wtot, y - row_h * i)
			cx = x
			for wcol in col_w[:-1]:
				cx += wcol
				c.line(cx, y, cx, y - Ht)
			for r, row in enumerate(rows):
				cy = y - row_h * (r + 1) + 5
				cx = x + 4
				for j, cell in enumerate(row):
					c.drawString(cx, cy, str(cell))
					cx += col_w[j]
			return y - Ht - 10

		y = table(left, y, [220, 140, 120], 18, [
			['項目', '値', '単位'],
			['後軸重量 WR', f"{v['WR']:.0f}", 'kg'],
			['ばね下重量 Wu', f"{v['Wu']:.0f}", 'kg'],
			['ばね上重量 Wr', f"{v['Wr']:.0f}", 'kg'],
			['ばね本数', f"{v['spring_count']}", '本'],
			['ばね1本当たり W', f"{v['W_per']:.0f}", 'kg'],
			['ばね幅 b', f"{v['b']:.0f}", 'mm'],
			['板厚 t', f"{v['t']:.0f}", 'mm'],
			['枚数 n', f"{v['n']}", '枚'],
			['有効スパン l', f"{v['l']:.0f}", 'mm'],
			['Uボルト間隔 l1', f"{v['l1']:.0f}", 'mm'],
		])

		y = table(left, y, [220, 140, 120], 18, [
			['材質', v.get('material', ''), ''],
			['引張り強さ σB', f"{v['sigma_b']:.0f}", 'N/mm²'],
			['降伏強さ σY', f"{v['sigma_y']:.0f}", 'N/mm²'],
		])

		c.setFont(font, 10)
		c.drawString(left, y, 'ばね応力')
		y -= 14
		c.setFont(font, 9)
		c.drawString(left, y, 'σ = (3×W×(l−l1)) / (2×b×t²×n) × g')
		y -= 12
		c.drawString(left, y, f"g = {v['g']:.1f} m/s²")
		y -= 14
		c.setFont(font, 11)
		c.drawString(left, y, f"σ = {v['sigma']:.2f} N/mm²")
		y -= 20

		c.setFont(font, 10)
		c.drawString(left, y, '安全率')
		y -= 14
		c.setFont(font, 9)
		c.drawString(left, y, f"破壊安全率 fb = σB / ({v['k']:.1f}×σ) = {v['fb']:.2f}  (基準 1.6以上)")
		y -= 12
		c.drawString(left, y, f"降伏安全率 fy = σY / ({v['k']:.1f}×σ) = {v['fy']:.2f}  (基準 1.3以上)")
		y -= 18
		c.setFont(font, 10)
		judge = 'OK' if (v.get('ok_fb') and v.get('ok_fy')) else 'NG'
		c.drawString(left, y, f"判定: {judge}")

		c.showPage()
		c.save()

	def get_state(self) -> dict:
		return {
			'WR_total': self.WR_total.GetValue(),
			'Wu_unsprung': self.Wu_unsprung.GetValue(),
			'spring_count': self.spring_count.GetValue(),
			'b_width': self.b_width.GetValue(),
			't_thickness': self.t_thickness.GetValue(),
			'n_leaves': self.n_leaves.GetValue(),
			'l_span': self.l_span.GetValue(),
			'l1_ubolt': self.l1_ubolt.GetValue(),
			'material': self.material.GetValue(),
			'sigma_b': self.sigma_b.GetValue(),
			'sigma_y': self.sigma_y.GetValue(),
			'description': self.description.GetValue(),
			'last': self.last,
		}

	def set_state(self, state: dict) -> None:
		if not state:
			return
		self.WR_total.SetValue(str(state.get('WR_total', self.WR_total.GetValue())))
		self.Wu_unsprung.SetValue(str(state.get('Wu_unsprung', self.Wu_unsprung.GetValue())))
		self.spring_count.SetValue(str(state.get('spring_count', self.spring_count.GetValue())))
		self.b_width.SetValue(str(state.get('b_width', self.b_width.GetValue())))
		self.t_thickness.SetValue(str(state.get('t_thickness', self.t_thickness.GetValue())))
		self.n_leaves.SetValue(str(state.get('n_leaves', self.n_leaves.GetValue())))
		self.l_span.SetValue(str(state.get('l_span', self.l_span.GetValue())))
		self.l1_ubolt.SetValue(str(state.get('l1_ubolt', self.l1_ubolt.GetValue())))
		self.material.SetValue(str(state.get('material', self.material.GetValue())))
		self.sigma_b.SetValue(str(state.get('sigma_b', self.sigma_b.GetValue())))
		self.sigma_y.SetValue(str(state.get('sigma_y', self.sigma_y.GetValue())))
		self.description.SetValue(str(state.get('description', self.description.GetValue())))
		self.last = state.get('last', self.last)
		self.btn_pdf.Enable(self.last is not None)


class OverviewPanel(wx.Panel):
	"""概要等説明書・装置の概要発行パネル"""
	def __init__(self, parent):
		super().__init__(parent)
		self.data = OverviewData()
		self.parent_frame = parent
		
		main_sizer = wx.BoxSizer(wx.VERTICAL)
		
		# タイトル
		title = wx.StaticText(self, label='概要等説明書・装置の概要')
		title_font = title.GetFont()
		title_font.PointSize += 3
		title_font = title_font.Bold()
		title.SetFont(title_font)
		main_sizer.Add(title, 0, wx.ALL, 10)
		
		# スクロール可能な入力エリア
		scroll = wx.ScrolledWindow(self, style=wx.VSCROLL)
		scroll.SetScrollRate(0, 20)
		scroll_sizer = wx.BoxSizer(wx.VERTICAL)
		
		# 基本情報セクション
		self._add_section(scroll_sizer, "基本情報", scroll)
		self.application_date = self._add_field(scroll, scroll_sizer, "申請日", "")
		self.applicant_name = self._add_field(scroll, scroll_sizer, "申請者名", "")
		self.vehicle_name = self._add_field(scroll, scroll_sizer, "車名", "")
		self.approval_number = self._add_field(scroll, scroll_sizer, "型式認定番号", "")
		
		# 寸法情報セクション
		self._add_section(scroll_sizer, "寸法情報 (mm)", scroll)
		self.length = self._add_field(scroll, scroll_sizer, "長さ", "")
		self.width = self._add_field(scroll, scroll_sizer, "幅", "")
		self.height = self._add_field(scroll, scroll_sizer, "高さ", "")
		self.wheelbase = self._add_field(scroll, scroll_sizer, "ホイールベース", "")
		self.tread_front = self._add_field(scroll, scroll_sizer, "トレッド（前）", "")
		self.tread_rear = self._add_field(scroll, scroll_sizer, "トレッド（後）", "")
		
		# 重量情報セクション
		self._add_section(scroll_sizer, "重量情報 (kg)", scroll)
		self.vehicle_weight = self._add_field(scroll, scroll_sizer, "車両重量", "")
		self.vehicle_total_weight = self._add_field(scroll, scroll_sizer, "車両総重量", "")
		self.max_load_weight = self._add_field(scroll, scroll_sizer, "最大積載量", "")
		
		# 車軸情報セクション
		self._add_section(scroll_sizer, "車軸情報", scroll)
		self.axle_count = self._add_field(scroll, scroll_sizer, "車軸数", "")
		self.front_axle_weight = self._add_field(scroll, scroll_sizer, "前軸重 (kg)", "")
		self.rear_axle_weight = self._add_field(scroll, scroll_sizer, "後軸重 (kg)", "")
		self.tire_size_front = self._add_field(scroll, scroll_sizer, "前輪タイヤサイズ", "")
		self.tire_size_rear = self._add_field(scroll, scroll_sizer, "後輪タイヤサイズ", "")
		
		# 装置説明セクション
		self._add_section(scroll_sizer, "装置説明", scroll)
		self.purpose = self._add_field(scroll, scroll_sizer, "目的", "")
		self.vehicle_type_description = self._add_field(scroll, scroll_sizer, "車種及び車体", "")
		self.engine_description = self._add_field(scroll, scroll_sizer, "原動機", "")
		self.transmission_description = self._add_field(scroll, scroll_sizer, "動力伝達装置", "")
		self.brake_description = self._add_field(scroll, scroll_sizer, "制動装置", "")
		self.suspension_description = self._add_field(scroll, scroll_sizer, "緩衝装置", "")
		self.fuel_description = self._add_field(scroll, scroll_sizer, "燃料装置", "")
		
		scroll.SetSizer(scroll_sizer)
		main_sizer.Add(scroll, 1, wx.EXPAND|wx.ALL, 5)
		
		# ボタンエリア
		btn_sizer = wx.BoxSizer(wx.HORIZONTAL)
		
		self.btn_auto_fill = wx.Button(self, label='計算結果から自動入力')
		self.btn_auto_fill.Bind(wx.EVT_BUTTON, self.on_auto_fill)
		btn_sizer.Add(self.btn_auto_fill, 0, wx.ALL, 5)
		
		btn_sizer.AddStretchSpacer()
		
		self.btn_preview = wx.Button(self, label='プレビュー')
		self.btn_preview.Bind(wx.EVT_BUTTON, self.on_preview)
		btn_sizer.Add(self.btn_preview, 0, wx.ALL, 5)
		
		self.btn_export = wx.Button(self, label='PDF発行...')
		self.btn_export.Bind(wx.EVT_BUTTON, self.on_export)
		btn_sizer.Add(self.btn_export, 0, wx.ALL, 5)
		
		main_sizer.Add(btn_sizer, 0, wx.EXPAND|wx.ALL, 10)
		
		self.SetSizer(main_sizer)
	
	def _add_section(self, sizer, title, parent):
		"""セクションタイトルを追加"""
		section_label = wx.StaticText(parent, label=title)
		font = section_label.GetFont()
		font.PointSize += 1
		font = font.Bold()
		section_label.SetFont(font)
		sizer.Add(section_label, 0, wx.ALL|wx.TOP, 10)
		sizer.Add(wx.StaticLine(parent), 0, wx.EXPAND|wx.LEFT|wx.RIGHT, 5)
	
	def _add_field(self, parent, sizer, label, default_value=""):
		"""入力フィールドを追加"""
		h_sizer = wx.BoxSizer(wx.HORIZONTAL)
		label_widget = wx.StaticText(parent, label=label, size=wx.Size(150, -1))
		h_sizer.Add(label_widget, 0, wx.ALIGN_CENTER_VERTICAL|wx.ALL, 5)
		
		text_ctrl = wx.TextCtrl(parent, value="", size=wx.Size(300, -1))
		if default_value:
			text_ctrl.SetHint(default_value)
		h_sizer.Add(text_ctrl, 1, wx.EXPAND|wx.ALL, 5)
		
		sizer.Add(h_sizer, 0, wx.EXPAND)
		return text_ctrl
	
	def on_auto_fill(self, event):
		"""計算結果から自動入力"""
		try:
			# 親フレームから全パネルを取得
			main_frame = self._get_main_frame()
			if not main_frame:
				wx.MessageBox('親フレームが見つかりません', 'エラー', wx.ICON_ERROR)
				return
			
			# プログレスダイアログを表示
			progress = wx.ProgressDialog(
				'自動計算中',
				'各パネルの計算を実行しています...',
				maximum=len(main_frame.panels),
				parent=self,
				style=wx.PD_APP_MODAL | wx.PD_AUTO_HIDE
			)
			
			# 各パネルで未計算の場合は自動計算を実行
			calc_count = 0
			for idx, (title, panel) in enumerate(main_frame.panels):
				progress.Update(idx, f'{title}を確認中...')
				
				# 概要等説明書パネル自身はスキップ
				if isinstance(panel, OverviewPanel):
					continue
				
				# 計算実行メソッドがあれば実行
				if hasattr(panel, 'on_calc'):
					try:
						sig = inspect.signature(panel.on_calc)
						params = list(sig.parameters.values())
						
						if len(params) == 0 or (len(params) == 1 and params[0].default != inspect.Parameter.empty):
							panel.on_calc(None)
							calc_count += 1
						elif len(params) == 1:
							panel.on_calc(None)
							calc_count += 1
						else:
							try:
								panel.on_calc()
								calc_count += 1
							except TypeError:
								pass
					except Exception as e:
						print(f"計算エラー ({title}): {e}")
						pass
			
			progress.Update(len(main_frame.panels), '計算完了。データを収集中...')
			
			# 計算データを収集
			collected = collect_calculation_data(main_frame.panels)
			
			# データを自動生成
			auto_data = auto_fill_overview_data(collected)
			
			progress.Destroy()
			
			# フィールドに反映
			if auto_data.vehicle_name:
				self.vehicle_name.SetValue(auto_data.vehicle_name)
			if auto_data.length:
				self.length.SetValue(auto_data.length)
			if auto_data.width:
				self.width.SetValue(auto_data.width)
			if auto_data.height:
				self.height.SetValue(auto_data.height)
			if auto_data.wheelbase:
				self.wheelbase.SetValue(auto_data.wheelbase)
			if auto_data.tread_front:
				self.tread_front.SetValue(auto_data.tread_front)
			if auto_data.tread_rear:
				self.tread_rear.SetValue(auto_data.tread_rear)
			if auto_data.vehicle_weight:
				self.vehicle_weight.SetValue(auto_data.vehicle_weight)
			if auto_data.vehicle_total_weight:
				self.vehicle_total_weight.SetValue(auto_data.vehicle_total_weight)
			if auto_data.max_load_weight:
				self.max_load_weight.SetValue(auto_data.max_load_weight)
			if auto_data.front_axle_weight:
				self.front_axle_weight.SetValue(auto_data.front_axle_weight)
			if auto_data.rear_axle_weight:
				self.rear_axle_weight.SetValue(auto_data.rear_axle_weight)
			if auto_data.axle_count:
				self.axle_count.SetValue(auto_data.axle_count)
			if auto_data.tire_size_front:
				self.tire_size_front.SetValue(auto_data.tire_size_front)
			if auto_data.tire_size_rear:
				self.tire_size_rear.SetValue(auto_data.tire_size_rear)
			if auto_data.purpose:
				self.purpose.SetValue(auto_data.purpose)
			
			msg = f'自動計算と入力が完了しました。\n\n'
			msg += f'実行した計算: {calc_count}個のパネル\n'
			msg += f'\n内容を確認して、必要に応じて修正してください。'
			wx.MessageBox(msg, '自動入力完了', wx.ICON_INFORMATION)
		
		except Exception as e:
			wx.MessageBox(f'自動入力エラー: {e}', 'エラー', wx.ICON_ERROR)
	
	def on_preview(self, event):
		"""プレビュー表示"""
		try:
			data = self._collect_form_data()
			preview_text = self._format_preview(data)
			show_result('概要等説明書 プレビュー', preview_text)
		except Exception as e:
			wx.MessageBox(f'プレビュー生成エラー: {e}', 'エラー', wx.ICON_ERROR)
	
	def on_export(self, event):
		"""PDF発行"""
		if not _REPORTLAB_AVAILABLE:
			wx.MessageBox('ReportLabが未インストールです。', 'PDF出力不可', wx.ICON_ERROR)
			return
		
		with wx.FileDialog(self, '概要等説明書PDFを保存', 
						   wildcard='PDF files (*.pdf)|*.pdf',
						   style=wx.FD_SAVE|wx.FD_OVERWRITE_PROMPT,
						   defaultFile='概要等説明書.pdf') as dlg:
			if dlg.ShowModal() != wx.ID_OK:
				return
			output_path = dlg.GetPath()
		
		try:
			data = self._collect_form_data()
			
			# テンプレートPDFのパスを確認
			template_path = self._find_template_pdf()
			
			generate_overview_pdf(data, output_path, template_path)
			
			msg = f'概要等説明書PDFを発行しました:\n{output_path}'
			if template_path:
				msg += '\n\n（テンプレートPDFを使用）'
			else:
				msg += '\n\n（テンプレートなしで新規作成）'
			
			wx.MessageBox(msg, '完了', wx.ICON_INFORMATION)
		
		except Exception as e:
			wx.MessageBox(f'PDF発行エラー: {e}', 'エラー', wx.ICON_ERROR)
	
	def _find_template_pdf(self) -> Optional[str]:
		"""テンプレートPDFを検索"""
		search_paths = [
			os.path.join(os.path.expanduser('~'), 'Desktop', 
						 '2025-1119-九州運輸局より', '申請書等', 
						 '概要等説明書.pdf'),
			os.path.join(os.path.expanduser('~'), 'Documents', 
						 '2025-1119-九州運輸局より', '申請書等', 
						 '概要等説明書.pdf'),
			os.path.join(os.path.dirname(os.path.abspath(__file__)),
						 'templates', '概要等説明書.pdf'),
			'概要等説明書.pdf',
		]
		
		for path in search_paths:
			if os.path.exists(path):
				return path
		
		return None
	
	def _collect_form_data(self) -> OverviewData:
		"""現在の入力からOverviewDataを生成"""
		data = OverviewData()
		data.application_date = self.application_date.GetValue()
		data.applicant_name = self.applicant_name.GetValue()
		data.vehicle_name = self.vehicle_name.GetValue()
		data.approval_number = self.approval_number.GetValue()
		data.length = self.length.GetValue()
		data.width = self.width.GetValue()
		data.height = self.height.GetValue()
		data.wheelbase = self.wheelbase.GetValue()
		data.tread_front = self.tread_front.GetValue()
		data.tread_rear = self.tread_rear.GetValue()
		data.vehicle_weight = self.vehicle_weight.GetValue()
		data.vehicle_total_weight = self.vehicle_total_weight.GetValue()
		data.max_load_weight = self.max_load_weight.GetValue()
		data.axle_count = self.axle_count.GetValue()
		data.front_axle_weight = self.front_axle_weight.GetValue()
		data.rear_axle_weight = self.rear_axle_weight.GetValue()
		data.tire_size_front = self.tire_size_front.GetValue()
		data.tire_size_rear = self.tire_size_rear.GetValue()
		data.purpose = self.purpose.GetValue()
		data.vehicle_type_description = self.vehicle_type_description.GetValue()
		data.engine_description = self.engine_description.GetValue()
		data.transmission_description = self.transmission_description.GetValue()
		data.brake_description = self.brake_description.GetValue()
		data.suspension_description = self.suspension_description.GetValue()
		data.fuel_description = self.fuel_description.GetValue()
		return data
	
	def _format_preview(self, data: OverviewData) -> str:
		"""プレビュー用のテキスト整形"""
		lines = [
			"=" * 50,
			"概要等説明書・装置の概要",
			"=" * 50,
			"",
			f"申請日: {data.application_date}",
			f"申請者: {data.applicant_name}",
			f"車名: {data.vehicle_name}",
			f"型式認定番号: {data.approval_number}",
			"",
			"【寸法情報】",
			f"  長さ: {data.length} mm",
			f"  幅: {data.width} mm",
			f"  高さ: {data.height} mm",
			f"  ホイールベース: {data.wheelbase} mm",
			f"  トレッド（前）: {data.tread_front} mm",
			f"  トレッド（後）: {data.tread_rear} mm",
			"",
			"【重量情報】",
			f"  車両重量: {data.vehicle_weight} kg",
			f"  車両総重量: {data.vehicle_total_weight} kg",
			f"  最大積載量: {data.max_load_weight} kg",
			"",
			"【車軸情報】",
			f"  車軸数: {data.axle_count}",
			f"  前軸重: {data.front_axle_weight} kg",
			f"  後軸重: {data.rear_axle_weight} kg",
			f"  前輪タイヤ: {data.tire_size_front}",
			f"  後輪タイヤ: {data.tire_size_rear}",
			"",
			"【装置説明】",
			f"  目的: {data.purpose}",
			f"  車種及び車体: {data.vehicle_type_description}",
			f"  原動機: {data.engine_description}",
			f"  動力伝達装置: {data.transmission_description}",
			f"  制動装置: {data.brake_description}",
			f"  緩衝装置: {data.suspension_description}",
			f"  燃料装置: {data.fuel_description}",
			"",
			"=" * 50,
		]
		return "\n".join(lines)
	
	def _get_main_frame(self):
		"""MainFrameを取得"""
		parent = self.GetParent()
		while parent:
			if isinstance(parent, MainFrame):
				return parent
			parent = parent.GetParent()
		return None
	
	def get_state(self) -> dict:
		"""状態を保存"""
		return {
			'application_date': self.application_date.GetValue(),
			'applicant_name': self.applicant_name.GetValue(),
			'vehicle_name': self.vehicle_name.GetValue(),
			'approval_number': self.approval_number.GetValue(),
			'length': self.length.GetValue(),
			'width': self.width.GetValue(),
			'height': self.height.GetValue(),
			'wheelbase': self.wheelbase.GetValue(),
			'tread_front': self.tread_front.GetValue(),
			'tread_rear': self.tread_rear.GetValue(),
			'vehicle_weight': self.vehicle_weight.GetValue(),
			'vehicle_total_weight': self.vehicle_total_weight.GetValue(),
			'max_load_weight': self.max_load_weight.GetValue(),
			'axle_count': self.axle_count.GetValue(),
			'front_axle_weight': self.front_axle_weight.GetValue(),
			'rear_axle_weight': self.rear_axle_weight.GetValue(),
			'tire_size_front': self.tire_size_front.GetValue(),
			'tire_size_rear': self.tire_size_rear.GetValue(),
			'purpose': self.purpose.GetValue(),
			'vehicle_type_description': self.vehicle_type_description.GetValue(),
			'engine_description': self.engine_description.GetValue(),
			'transmission_description': self.transmission_description.GetValue(),
			'brake_description': self.brake_description.GetValue(),
			'suspension_description': self.suspension_description.GetValue(),
			'fuel_description': self.fuel_description.GetValue(),
		}
	
	def set_state(self, state: dict):
		"""状態を復元"""
		if not state:
			return
		if 'application_date' in state:
			self.application_date.SetValue(state['application_date'])
		if 'applicant_name' in state:
			self.applicant_name.SetValue(state['applicant_name'])
		if 'vehicle_name' in state:
			self.vehicle_name.SetValue(state['vehicle_name'])
		if 'approval_number' in state:
			self.approval_number.SetValue(state['approval_number'])
		if 'length' in state:
			self.length.SetValue(state['length'])
		if 'width' in state:
			self.width.SetValue(state['width'])
		if 'height' in state:
			self.height.SetValue(state['height'])
		if 'wheelbase' in state:
			self.wheelbase.SetValue(state['wheelbase'])
		if 'tread_front' in state:
			self.tread_front.SetValue(state['tread_front'])
		if 'tread_rear' in state:
			self.tread_rear.SetValue(state['tread_rear'])
		if 'vehicle_weight' in state:
			self.vehicle_weight.SetValue(state['vehicle_weight'])
		if 'vehicle_total_weight' in state:
			self.vehicle_total_weight.SetValue(state['vehicle_total_weight'])
		if 'max_load_weight' in state:
			self.max_load_weight.SetValue(state['max_load_weight'])
		if 'axle_count' in state:
			self.axle_count.SetValue(state['axle_count'])
		if 'front_axle_weight' in state:
			self.front_axle_weight.SetValue(state['front_axle_weight'])
		if 'rear_axle_weight' in state:
			self.rear_axle_weight.SetValue(state['rear_axle_weight'])
		if 'tire_size_front' in state:
			self.tire_size_front.SetValue(state['tire_size_front'])
		if 'tire_size_rear' in state:
			self.tire_size_rear.SetValue(state['tire_size_rear'])
		if 'purpose' in state:
			self.purpose.SetValue(state['purpose'])
		if 'vehicle_type_description' in state:
			self.vehicle_type_description.SetValue(state['vehicle_type_description'])
		if 'engine_description' in state:
			self.engine_description.SetValue(state['engine_description'])
		if 'transmission_description' in state:
			self.transmission_description.SetValue(state['transmission_description'])
		if 'brake_description' in state:
			self.brake_description.SetValue(state['brake_description'])
		if 'suspension_description' in state:
			self.suspension_description.SetValue(state['suspension_description'])
		if 'fuel_description' in state:
			self.fuel_description.SetValue(state['fuel_description'])
	
	def export_to_path(self, path):
		"""指定パスにPDFを出力（一括出力用）"""
		try:
			data = self._collect_form_data()
			
			# テンプレートPDFのパスを確認
			template_path = self._find_template_pdf()
			
			generate_overview_pdf(data, path, template_path)
		except Exception:
			pass


class Form1Panel(wx.Panel):
	"""第1号様式（組立車）発行パネル"""
	def __init__(self, parent):
		super().__init__(parent)
		self.data = Form1Data()
		self.parent_frame = parent
		
		main_sizer = wx.BoxSizer(wx.VERTICAL)
		
		# タイトル
		title = wx.StaticText(self, label='第1号様式（組立車等届出書）発行')
		title_font = title.GetFont()
		title_font.PointSize += 3
		title_font = title_font.Bold()
		title.SetFont(title_font)
		main_sizer.Add(title, 0, wx.ALL, 10)
		
		# スクロール可能な入力エリア
		scroll = wx.ScrolledWindow(self, style=wx.VSCROLL)
		scroll.SetScrollRate(0, 20)
		scroll_sizer = wx.BoxSizer(wx.VERTICAL)
		
		# 申請者情報セクション
		self._add_section(scroll_sizer, "申請者情報", scroll)
		self.applicant_name = self._add_field(scroll, scroll_sizer, "氏名又は名称", "")
		self.applicant_address = self._add_field(scroll, scroll_sizer, "住所", "")
		self.application_date = self._add_field(scroll, scroll_sizer, "申請日", "")
		
		# 車両基本情報セクション
		self._add_section(scroll_sizer, "車両基本情報", scroll)
		self.vehicle_type = self._add_field(scroll, scroll_sizer, "自動車の種別", "")
		self.vehicle_name = self._add_field(scroll, scroll_sizer, "自動車の名称", "")
		self.vehicle_model = self._add_field(scroll, scroll_sizer, "型式", "")
		
		# 寸法情報セクション
		self._add_section(scroll_sizer, "寸法情報 (mm)", scroll)
		self.length = self._add_field(scroll, scroll_sizer, "長さ", "")
		self.width = self._add_field(scroll, scroll_sizer, "幅", "")
		self.height = self._add_field(scroll, scroll_sizer, "高さ", "")
		self.wheelbase = self._add_field(scroll, scroll_sizer, "ホイールベース", "")
		self.tread_front = self._add_field(scroll, scroll_sizer, "トレッド（前）", "")
		self.tread_rear = self._add_field(scroll, scroll_sizer, "トレッド（後）", "")
		
		# 重量情報セクション
		self._add_section(scroll_sizer, "重量情報 (kg)", scroll)
		self.vehicle_weight = self._add_field(scroll, scroll_sizer, "車両重量", "")
		self.vehicle_total_weight = self._add_field(scroll, scroll_sizer, "車両総重量", "")
		self.max_load_weight = self._add_field(scroll, scroll_sizer, "最大積載量", "")
		
		# 車軸情報セクション
		self._add_section(scroll_sizer, "車軸情報", scroll)
		self.axle_count = self._add_field(scroll, scroll_sizer, "車軸数", "")
		self.axle_weight_front = self._add_field(scroll, scroll_sizer, "前軸重 (kg)", "")
		self.axle_weight_rear = self._add_field(scroll, scroll_sizer, "後軸重 (kg)", "")
		
		scroll.SetSizer(scroll_sizer)
		main_sizer.Add(scroll, 1, wx.EXPAND|wx.ALL, 5)
		
		# ボタンエリア
		btn_sizer = wx.BoxSizer(wx.HORIZONTAL)
		
		self.btn_auto_fill = wx.Button(self, label='計算結果から自動入力')
		self.btn_auto_fill.Bind(wx.EVT_BUTTON, self.on_auto_fill)
		btn_sizer.Add(self.btn_auto_fill, 0, wx.ALL, 5)
		
		self.btn_clear = wx.Button(self, label='入力クリア')
		self.btn_clear.Bind(wx.EVT_BUTTON, self.on_clear)
		btn_sizer.Add(self.btn_clear, 0, wx.ALL, 5)
		
		btn_sizer.AddStretchSpacer()
		
		self.btn_preview = wx.Button(self, label='プレビュー')
		self.btn_preview.Bind(wx.EVT_BUTTON, self.on_preview)
		btn_sizer.Add(self.btn_preview, 0, wx.ALL, 5)
		
		self.btn_export = wx.Button(self, label='PDF発行...')
		self.btn_export.Bind(wx.EVT_BUTTON, self.on_export)
		btn_sizer.Add(self.btn_export, 0, wx.ALL, 5)
		
		main_sizer.Add(btn_sizer, 0, wx.EXPAND|wx.ALL, 10)
		
		self.SetSizer(main_sizer)
	
	def _add_section(self, sizer, title, parent):
		"""セクションタイトルを追加"""
		section_label = wx.StaticText(parent, label=title)
		font = section_label.GetFont()
		font.PointSize += 1
		font = font.Bold()
		section_label.SetFont(font)
		sizer.Add(section_label, 0, wx.ALL|wx.TOP, 10)
		sizer.Add(wx.StaticLine(parent), 0, wx.EXPAND|wx.LEFT|wx.RIGHT, 5)
	
	def _add_field(self, parent, sizer, label, default_value=""):
		"""入力フィールドを追加"""
		h_sizer = wx.BoxSizer(wx.HORIZONTAL)
		label_widget = wx.StaticText(parent, label=label, size=wx.Size(150, -1))
		h_sizer.Add(label_widget, 0, wx.ALIGN_CENTER_VERTICAL|wx.ALL, 5)
		
		text_ctrl = wx.TextCtrl(parent, value="", size=wx.Size(300, -1))
		if default_value:
			text_ctrl.SetHint(default_value)
		h_sizer.Add(text_ctrl, 1, wx.EXPAND|wx.ALL, 5)
		
		sizer.Add(h_sizer, 0, wx.EXPAND)
		return text_ctrl
	
	def on_auto_fill(self, event):
		"""計算結果から自動入力"""
		try:
			# 親フレームから全パネルを取得
			main_frame = self._get_main_frame()
			if not main_frame:
				wx.MessageBox('親フレームが見つかりません', 'エラー', wx.ICON_ERROR)
				return
			
			# プログレスダイアログを表示
			progress = wx.ProgressDialog(
				'自動計算中',
				'各パネルの計算を実行しています...',
				maximum=len(main_frame.panels),
				parent=self,
				style=wx.PD_APP_MODAL | wx.PD_AUTO_HIDE
			)
			
			# 各パネルで未計算の場合は自動計算を実行
			calc_count = 0
			for idx, (title, panel) in enumerate(main_frame.panels):
				progress.Update(idx, f'{title}を確認中...')
				
				# 第1号様式パネル自身はスキップ
				if isinstance(panel, Form1Panel):
					continue
				
				# 計算実行メソッドがあれば実行
				if hasattr(panel, 'on_calc'):
					try:
						# 計算を実行（引数なしまたはNoneで呼び出せるか確認）
						import inspect
						sig = inspect.signature(panel.on_calc)
						params = list(sig.parameters.values())
						
						# 引数が1つ（self以外の引数が0個）または引数が2つでデフォルト値がある場合
						if len(params) == 0 or (len(params) == 1 and params[0].default != inspect.Parameter.empty):
							panel.on_calc(None)
							calc_count += 1
						elif len(params) == 1:
							panel.on_calc(None)
							calc_count += 1
						else:
							# 引数なしで呼べる場合（TwoAxleLeafSpringPanel等）
							try:
								panel.on_calc()
								calc_count += 1
							except TypeError:
								pass
					except Exception as e:
						# 計算エラーは無視して続行
						print(f"計算エラー ({title}): {e}")
						pass
			
			progress.Update(len(main_frame.panels), '計算完了。データを収集中...')
			
			# 計算データを収集
			collected = collect_calculation_data(main_frame.panels)
			
			# データを自動生成
			auto_data = auto_fill_form1_data(collected)
			
			progress.Destroy()
			
			# フィールドに反映
			if auto_data.vehicle_type:
				self.vehicle_type.SetValue(auto_data.vehicle_type)
			if auto_data.vehicle_name:
				self.vehicle_name.SetValue(auto_data.vehicle_name)
			if auto_data.vehicle_model:
				self.vehicle_model.SetValue(auto_data.vehicle_model)
			if auto_data.length:
				self.length.SetValue(auto_data.length)
			if auto_data.width:
				self.width.SetValue(auto_data.width)
			if auto_data.height:
				self.height.SetValue(auto_data.height)
			if auto_data.wheelbase:
				self.wheelbase.SetValue(auto_data.wheelbase)
			if auto_data.tread_front:
				self.tread_front.SetValue(auto_data.tread_front)
			if auto_data.tread_rear:
				self.tread_rear.SetValue(auto_data.tread_rear)
			if auto_data.vehicle_weight:
				self.vehicle_weight.SetValue(auto_data.vehicle_weight)
			if auto_data.vehicle_total_weight:
				self.vehicle_total_weight.SetValue(auto_data.vehicle_total_weight)
			if auto_data.max_load_weight:
				self.max_load_weight.SetValue(auto_data.max_load_weight)
			if auto_data.axle_count:
				self.axle_count.SetValue(auto_data.axle_count)
			if auto_data.axle_weight_front:
				self.axle_weight_front.SetValue(auto_data.axle_weight_front)
			if auto_data.axle_weight_rear:
				self.axle_weight_rear.SetValue(auto_data.axle_weight_rear)
			
			# 完了メッセージ
			msg = f'自動計算と入力が完了しました。\n\n'
			msg += f'実行した計算: {calc_count}個のパネル\n'
			msg += f'\n内容を確認して、必要に応じて修正してください。'
			wx.MessageBox(msg, '自動入力完了', wx.ICON_INFORMATION)
		
		except Exception as e:
			wx.MessageBox(f'自動入力エラー: {e}', 'エラー', wx.ICON_ERROR)
	
	def on_clear(self, event):
		"""入力をクリア"""
		if wx.MessageBox('入力内容をクリアしますか？', '確認', 
						 wx.YES_NO|wx.ICON_QUESTION) == wx.YES:
			# 基本項目のみクリア（申請日は残す）
			self.applicant_name.SetValue("")
			self.applicant_address.SetValue("")
			self.vehicle_name.SetValue("")
			self.vehicle_model.SetValue("")
			self.length.SetValue("")
			self.width.SetValue("")
			self.height.SetValue("")
			self.wheelbase.SetValue("")
			self.tread_front.SetValue("")
			self.tread_rear.SetValue("")
			self.vehicle_weight.SetValue("")
			self.vehicle_total_weight.SetValue("")
			self.max_load_weight.SetValue("")
			self.axle_count.SetValue("")
			self.axle_weight_front.SetValue("")
			self.axle_weight_rear.SetValue("")
	
	def on_preview(self, event):
		"""プレビュー表示"""
		try:
			data = self._collect_form_data()
			preview_text = self._format_preview(data)
			show_result('第1号様式 プレビュー', preview_text)
		except Exception as e:
			wx.MessageBox(f'プレビュー生成エラー: {e}', 'エラー', wx.ICON_ERROR)
	
	def on_export(self, event):
		"""PDF発行"""
		if not _REPORTLAB_AVAILABLE:
			wx.MessageBox('ReportLabが未インストールです。', 'PDF出力不可', wx.ICON_ERROR)
			return
		
		with wx.FileDialog(self, '第1号様式PDFを保存', 
						   wildcard='PDF files (*.pdf)|*.pdf',
						   style=wx.FD_SAVE|wx.FD_OVERWRITE_PROMPT,
						   defaultFile='第1号様式_組立車.pdf') as dlg:
			if dlg.ShowModal() != wx.ID_OK:
				return
			output_path = dlg.GetPath()
		
		try:
			data = self._collect_form_data()
			
			# テンプレートPDFのパスを確認（複数の場所を試す）
			template_path = self._find_template_pdf()
			
			generate_form1_pdf(data, output_path, template_path)
			
			msg = f'第1号様式PDFを発行しました:\n{output_path}'
			if template_path:
				msg += '\n\n（テンプレートPDFを使用）'
			else:
				msg += '\n\n（テンプレートなしで新規作成）'
			
			wx.MessageBox(msg, '完了', wx.ICON_INFORMATION)
		
		except Exception as e:
			wx.MessageBox(f'PDF発行エラー: {e}', 'エラー', wx.ICON_ERROR)
	
	def _find_template_pdf(self) -> Optional[str]:
		"""テンプレートPDFを検索"""
		# 検索候補パス
		search_paths = [
			# デスクトップ
			os.path.join(os.path.expanduser('~'), 'Desktop', 
						 '2025-1119-九州運輸局より', '申請書等', 
						 '【基本】組立車　第１号様式.pdf'),
			# ドキュメント
			os.path.join(os.path.expanduser('~'), 'Documents', 
						 '2025-1119-九州運輸局より', '申請書等', 
						 '【基本】組立車　第１号様式.pdf'),
			# プロジェクトフォルダ
			os.path.join(os.path.dirname(os.path.abspath(__file__)),
						 'templates', '【基本】組立車　第１号様式.pdf'),
			# 現在のディレクトリ
			'【基本】組立車　第１号様式.pdf',
		]
		
		for path in search_paths:
			if os.path.exists(path):
				return path
		
		return None
	
	def _collect_form_data(self) -> Form1Data:
		"""現在の入力からForm1Dataを生成"""
		data = Form1Data()
		data.applicant_name = self.applicant_name.GetValue()
		data.applicant_address = self.applicant_address.GetValue()
		data.application_date = self.application_date.GetValue()
		data.vehicle_type = self.vehicle_type.GetValue()
		data.vehicle_name = self.vehicle_name.GetValue()
		data.vehicle_model = self.vehicle_model.GetValue()
		data.length = self.length.GetValue()
		data.width = self.width.GetValue()
		data.height = self.height.GetValue()
		data.wheelbase = self.wheelbase.GetValue()
		data.tread_front = self.tread_front.GetValue()
		data.tread_rear = self.tread_rear.GetValue()
		data.vehicle_weight = self.vehicle_weight.GetValue()
		data.vehicle_total_weight = self.vehicle_total_weight.GetValue()
		data.max_load_weight = self.max_load_weight.GetValue()
		data.axle_count = self.axle_count.GetValue()
		data.axle_weight_front = self.axle_weight_front.GetValue()
		data.axle_weight_rear = self.axle_weight_rear.GetValue()
		return data
	
	def _format_preview(self, data: Form1Data) -> str:
		"""プレビュー用のテキスト整形"""
		lines = [
			"=" * 50,
			"第1号様式（組立車等届出書）",
			"=" * 50,
			"",
			f"申請日: {data.application_date}",
			f"氏名又は名称: {data.applicant_name}",
			f"住所: {data.applicant_address}",
			"",
			"【車両基本情報】",
			f"  自動車の種別: {data.vehicle_type}",
			f"  自動車の名称: {data.vehicle_name}",
			f"  型式: {data.vehicle_model}",
			"",
			"【寸法情報】",
			f"  長さ: {data.length} mm",
			f"  幅: {data.width} mm",
			f"  高さ: {data.height} mm",
			f"  ホイールベース: {data.wheelbase} mm",
			f"  トレッド（前）: {data.tread_front} mm",
			f"  トレッド（後）: {data.tread_rear} mm",
			"",
			"【重量情報】",
			f"  車両重量: {data.vehicle_weight} kg",
			f"  車両総重量: {data.vehicle_total_weight} kg",
			f"  最大積載量: {data.max_load_weight} kg",
			"",
			"【車軸情報】",
			f"  車軸数: {data.axle_count}",
			f"  前軸重: {data.axle_weight_front} kg",
			f"  後軸重: {data.axle_weight_rear} kg",
]
		return "\n".join(lines)
	
	def _get_main_frame(self):
		"""MainFrameを取得"""
		parent = self.GetParent()
		while parent:
			if isinstance(parent, MainFrame):
				return parent
			parent = parent.GetParent()
		return None
	
	def get_state(self) -> dict:
		"""状態を保存"""
		return {
			'applicant_name': self.applicant_name.GetValue(),
			'applicant_address': self.applicant_address.GetValue(),
			'application_date': self.application_date.GetValue(),
			'vehicle_type': self.vehicle_type.GetValue(),
			'vehicle_name': self.vehicle_name.GetValue(),
			'vehicle_model': self.vehicle_model.GetValue(),
			'length': self.length.GetValue(),
			'width': self.width.GetValue(),
			'height': self.height.GetValue(),
			'wheelbase': self.wheelbase.GetValue(),
			'tread_front': self.tread_front.GetValue(),
			'tread_rear': self.tread_rear.GetValue(),
			'vehicle_weight': self.vehicle_weight.GetValue(),
			'vehicle_total_weight': self.vehicle_total_weight.GetValue(),
			'max_load_weight': self.max_load_weight.GetValue(),
			'axle_count': self.axle_count.GetValue(),
			'axle_weight_front': self.axle_weight_front.GetValue(),
			'axle_weight_rear': self.axle_weight_rear.GetValue(),
		}
	
	def set_state(self, state: dict):
		"""状態を復元"""
		if not state:
			return
		if 'applicant_name' in state:
			self.applicant_name.SetValue(state['applicant_name'])
		if 'applicant_address' in state:
			self.applicant_address.SetValue(state['applicant_address'])
		if 'application_date' in state:
			self.application_date.SetValue(state['application_date'])
		if 'vehicle_type' in state:
			self.vehicle_type.SetValue(state['vehicle_type'])
		if 'vehicle_name' in state:
			self.vehicle_name.SetValue(state['vehicle_name'])
		if 'vehicle_model' in state:
			self.vehicle_model.SetValue(state['vehicle_model'])
		if 'length' in state:
			self.length.SetValue(state['length'])
		if 'width' in state:
			self.width.SetValue(state['width'])
		if 'height' in state:
			self.height.SetValue(state['height'])
		if 'wheelbase' in state:
			self.wheelbase.SetValue(state['wheelbase'])
		if 'tread_front' in state:
			self.tread_front.SetValue(state['tread_front'])
		if 'tread_rear' in state:
			self.tread_rear.SetValue(state['tread_rear'])
		if 'vehicle_weight' in state:
			self.vehicle_weight.SetValue(state['vehicle_weight'])
		if 'vehicle_total_weight' in state:
			self.vehicle_total_weight.SetValue(state['vehicle_total_weight'])
		if 'max_load_weight' in state:
			self.max_load_weight.SetValue(state['max_load_weight'])
		if 'axle_count' in state:
			self.axle_count.SetValue(state['axle_count'])
		if 'axle_weight_front' in state:
			self.axle_weight_front.SetValue(state['axle_weight_front'])
		if 'axle_weight_rear' in state:
			self.axle_weight_rear.SetValue(state['axle_weight_rear'])
	
	def export_to_path(self, path):
		"""指定パスにPDFを出力（一括出力用）"""
		try:
			data = self._collect_form_data()
			
			# テンプレートPDFのパスを確認
			template_path = self._find_template_pdf()
			
			generate_form1_pdf(data, path, template_path)
		except Exception:
			pass


class Form2Panel(wx.Panel):
	"""保安基準適合検討表（ライトトレーラ用）発行パネル"""
	def __init__(self, parent):
		super().__init__(parent)
		self.data = Form2Data()
		self.parent_frame = parent
		
		main_sizer = wx.BoxSizer(wx.VERTICAL)
		
		# タイトル
		title = wx.StaticText(self, label='保安基準適合検討表（ライトトレーラ用）')
		title_font = title.GetFont()
		title_font.PointSize += 3
		title_font = title_font.Bold()
		title.SetFont(title_font)
		main_sizer.Add(title, 0, wx.ALL, 10)
		
		# スクロール可能な入力エリア
		scroll = wx.ScrolledWindow(self, style=wx.VSCROLL)
		scroll.SetScrollRate(0, 20)
		scroll_sizer = wx.BoxSizer(wx.VERTICAL)
		
		# 2条: 寸法
		self._add_section(scroll_sizer, "2条: 寸法", scroll)
		self.length = self._add_field(scroll, scroll_sizer, "長さ (mm)", "4700")
		self.width = self._add_field(scroll, scroll_sizer, "幅 (mm)", "1700")
		self.height = self._add_field(scroll, scroll_sizer, "高さ (mm)", "2000")
		
		# 3条・3条の2: 最低地上高・車台車体
		self._add_section(scroll_sizer, "3条・3条の2", scroll)
		self.ground_clearance = self._add_field(scroll, scroll_sizer, "最低地上高 (mm)", "100")
		self.chassis_structure = self._add_field(scroll, scroll_sizer, "車台構造", "鋼製フレーム構造")
		
		# 4条の2: 牽引
		self._add_section(scroll_sizer, "4条の2: 牽引", scroll)
		self.trailer_weight = self._add_field(scroll, scroll_sizer, "牽引重量 (kg)", "")
		self.coupler_type = self._add_field(scroll, scroll_sizer, "カプラー形式", "ボールカプラー")
		
		# 5条: 重量等
		self._add_section(scroll_sizer, "5条: 重量等", scroll)
		self.vehicle_weight = self._add_field(scroll, scroll_sizer, "車両重量 (kg)", "")
		self.axle_weight_front = self._add_field(scroll, scroll_sizer, "前軸重 (kg)", "")
		self.axle_weight_rear = self._add_field(scroll, scroll_sizer, "後軸重 (kg)", "")
		
		# 6条〜11条の4: 走行装置〜騒音
		self._add_section(scroll_sizer, "6条〜11条の4", scroll)
		self.tire_condition = self._add_field(scroll, scroll_sizer, "6条: タイヤ状態", "適合")
		self.has_engine = self._add_field(scroll, scroll_sizer, "7条: 原動機有無", "無し")
		self.fuel_system = self._add_field(scroll, scroll_sizer, "8条: 燃料装置", "該当なし")
		self.lubrication_system = self._add_field(scroll, scroll_sizer, "9条: 潤滑装置", "該当なし")
		self.exhaust_system = self._add_field(scroll, scroll_sizer, "10条: 排気管", "該当なし")
		self.emission_control = self._add_field(scroll, scroll_sizer, "11条: 排出ガス", "該当なし")
		
		# 12条〜21条
		self._add_section(scroll_sizer, "12条〜21条", scroll)
		self.parking_brake = self._add_field(scroll, scroll_sizer, "12条: 駐車ブレーキ", "適合")
		self.service_brake = self._add_field(scroll, scroll_sizer, "12条: 常用ブレーキ", "適合")
		self.suspension = self._add_field(scroll, scroll_sizer, "13条: 緩衝装置", "リーフスプリング式")
		self.coupling_device = self._add_field(scroll, scroll_sizer, "17条: 連結装置", "ボールカプラー式")
		self.safety_chain = self._add_field(scroll, scroll_sizer, "17条の2: 安全装置", "安全チェーン取付済み")
		self.cargo_device = self._add_field(scroll, scroll_sizer, "20条: 積載装置", "荷台付き")
		self.frame_body = self._add_field(scroll, scroll_sizer, "21条: 車枠車体", "鋼製フレーム")
		
		scroll.SetSizer(scroll_sizer)
		main_sizer.Add(scroll, 1, wx.EXPAND|wx.ALL, 5)
		
		# ボタンエリア
		btn_sizer = wx.BoxSizer(wx.HORIZONTAL)
		
		self.btn_auto_fill = wx.Button(self, label='自動入力')
		self.btn_auto_fill.Bind(wx.EVT_BUTTON, self.on_auto_fill)
		btn_sizer.Add(self.btn_auto_fill, 0, wx.ALL, 5)
		
		self.btn_clear = wx.Button(self, label='クリア')
		self.btn_clear.Bind(wx.EVT_BUTTON, self.on_clear)
		btn_sizer.Add(self.btn_clear, 0, wx.ALL, 5)
		
		self.btn_preview = wx.Button(self, label='プレビュー')
		self.btn_preview.Bind(wx.EVT_BUTTON, self.on_preview)
		btn_sizer.Add(self.btn_preview, 0, wx.ALL, 5)
		
		self.btn_export = wx.Button(self, label='PDF発行...')
		self.btn_export.Bind(wx.EVT_BUTTON, self.on_export)
		btn_sizer.Add(self.btn_export, 0, wx.ALL, 5)
		
		main_sizer.Add(btn_sizer, 0, wx.EXPAND|wx.ALL, 10)
		
		self.SetSizer(main_sizer)
	
	def _add_section(self, sizer, title, parent):
		"""セクションタイトルを追加"""
		section_label = wx.StaticText(parent, label=title)
		font = section_label.GetFont()
		font.PointSize += 1
		font = font.Bold()
		section_label.SetFont(font)
		sizer.Add(section_label, 0, wx.ALL|wx.TOP, 10)
		sizer.Add(wx.StaticLine(parent), 0, wx.EXPAND|wx.LEFT|wx.RIGHT, 5)
	
	def _add_field(self, parent, sizer, label, default_value=""):
		"""入力フィールドを追加"""
		h_sizer = wx.BoxSizer(wx.HORIZONTAL)
		label_widget = wx.StaticText(parent, label=label, size=wx.Size(150, -1))
		h_sizer.Add(label_widget, 0, wx.ALIGN_CENTER_VERTICAL|wx.ALL, 5)
		
		# プレースホルダー設定：初期値は空で、hint_textはプレースホルダーとして表示
		text_ctrl = wx.TextCtrl(parent, value="", size=wx.Size(300, -1))
		if default_value:
			text_ctrl.SetHint(default_value)
		h_sizer.Add(text_ctrl, 1, wx.EXPAND|wx.ALL, 5)
		
		sizer.Add(h_sizer, 0, wx.EXPAND)
		return text_ctrl
	
	def on_auto_fill(self, event):
		"""計算結果から自動入力"""
		try:
			# 親フレームから全パネルを取得
			main_frame = self._get_main_frame()
			if not main_frame:
				wx.MessageBox('親フレームが見つかりません', 'エラー', wx.ICON_ERROR)
				return
			
			# プログレスダイアログを表示
			progress = wx.ProgressDialog(
				'自動計算中',
				'各パネルの計算を実行しています...',
				maximum=len(main_frame.panels),
				parent=self,
				style=wx.PD_APP_MODAL | wx.PD_AUTO_HIDE
			)
			
			# 各パネルで未計算の場合は自動計算を実行
			calc_count = 0
			for idx, (title, panel) in enumerate(main_frame.panels):
				progress.Update(idx, f'{title}を確認中...')
				
				# Form2Panelパネル自身はスキップ
				if isinstance(panel, Form2Panel):
					continue
				
				# 計算実行メソッドがあれば実行
				if hasattr(panel, 'on_calc'):
					try:
						import inspect
						sig = inspect.signature(panel.on_calc)
						params = list(sig.parameters.values())
						
						if len(params) == 0 or (len(params) == 1 and params[0].default != inspect.Parameter.empty):
							panel.on_calc(None)
							calc_count += 1
						elif len(params) == 1:
							panel.on_calc(None)
							calc_count += 1
						else:
							try:
								panel.on_calc()
								calc_count += 1
							except TypeError:
								pass
					except Exception as e:
						print(f"計算エラー ({title}): {e}")
						pass
			
			progress.Update(len(main_frame.panels), '計算完了。データを収集中...')
			
			# 計算データを収集
			collected = collect_calculation_data(main_frame.panels)
			
			# データを自動生成
			auto_data = auto_fill_form2_data(collected)
			
			progress.Destroy()
			
			# フィールドに反映
			if auto_data.length:
				self.length.SetValue(auto_data.length)
			if auto_data.width:
				self.width.SetValue(auto_data.width)
			if auto_data.height:
				self.height.SetValue(auto_data.height)
			if auto_data.ground_clearance:
				self.ground_clearance.SetValue(auto_data.ground_clearance)
			if auto_data.chassis_structure:
				self.chassis_structure.SetValue(auto_data.chassis_structure)
			if auto_data.trailer_weight:
				self.trailer_weight.SetValue(auto_data.trailer_weight)
			if auto_data.coupler_type:
				self.coupler_type.SetValue(auto_data.coupler_type)
			if auto_data.vehicle_weight:
				self.vehicle_weight.SetValue(auto_data.vehicle_weight)
			if auto_data.axle_weight_front:
				self.axle_weight_front.SetValue(auto_data.axle_weight_front)
			if auto_data.axle_weight_rear:
				self.axle_weight_rear.SetValue(auto_data.axle_weight_rear)
			if auto_data.tire_condition:
				self.tire_condition.SetValue(auto_data.tire_condition)
			if auto_data.has_engine:
				self.has_engine.SetValue(auto_data.has_engine)
			if auto_data.fuel_system:
				self.fuel_system.SetValue(auto_data.fuel_system)
			if auto_data.lubrication_system:
				self.lubrication_system.SetValue(auto_data.lubrication_system)
			if auto_data.exhaust_system:
				self.exhaust_system.SetValue(auto_data.exhaust_system)
			if auto_data.emission_control:
				self.emission_control.SetValue(auto_data.emission_control)
			if auto_data.parking_brake:
				self.parking_brake.SetValue(auto_data.parking_brake)
			if auto_data.service_brake:
				self.service_brake.SetValue(auto_data.service_brake)
			if auto_data.suspension:
				self.suspension.SetValue(auto_data.suspension)
			if auto_data.coupling_device:
				self.coupling_device.SetValue(auto_data.coupling_device)
			if auto_data.safety_chain:
				self.safety_chain.SetValue(auto_data.safety_chain)
			if auto_data.cargo_device:
				self.cargo_device.SetValue(auto_data.cargo_device)
			if auto_data.frame_body:
				self.frame_body.SetValue(auto_data.frame_body)
			
			# 完了メッセージ
			msg = f'自動計算と入力が完了しました。\n\n'
			msg += f'実行した計算: {calc_count}個のパネル\n'
			msg += f'\n内容を確認して、必要に応じて修正してください。'
			wx.MessageBox(msg, '自動入力完了', wx.ICON_INFORMATION)
		
		except Exception as e:
			wx.MessageBox(f'自動入力エラー: {e}', 'エラー', wx.ICON_ERROR)
	
	def on_clear(self, event):
		"""入力をクリア"""
		if wx.MessageBox('入力内容をクリアしますか？', '確認', 
						 wx.YES_NO|wx.ICON_QUESTION) == wx.YES:
			# 入力項目をデフォルト値に戻す
			self.length.SetValue("")
			self.width.SetValue("")
			self.height.SetValue("")
			self.ground_clearance.SetValue("")
			self.chassis_structure.SetValue("")
			self.trailer_weight.SetValue("")
			self.coupler_type.SetValue("")
			self.vehicle_weight.SetValue("")
			self.axle_weight_front.SetValue("")
			self.axle_weight_rear.SetValue("")
			self.tire_condition.SetValue("")
			self.has_engine.SetValue("")
			self.fuel_system.SetValue("")
			self.lubrication_system.SetValue("")
			self.exhaust_system.SetValue("")
			self.emission_control.SetValue("")
			self.parking_brake.SetValue("")
			self.service_brake.SetValue("")
			self.suspension.SetValue("")
			self.coupling_device.SetValue("")
			self.safety_chain.SetValue("")
			self.cargo_device.SetValue("")
			self.frame_body.SetValue("")
	
	def on_preview(self, event):
		"""プレビュー表示"""
		try:
			data = self._collect_form_data()
			preview_text = self._format_preview(data)
			show_result('保安基準適合検討表 プレビュー', preview_text)
		except Exception as e:
			wx.MessageBox(f'プレビュー生成エラー: {e}', 'エラー', wx.ICON_ERROR)
	
	def on_export(self, event):
		"""PDF発行"""
		if not _REPORTLAB_AVAILABLE:
			wx.MessageBox('ReportLabが未インストールです。', 'PDF出力不可', wx.ICON_ERROR)
			return
		
		with wx.FileDialog(self, '保安基準適合検討表PDFを保存', 
						   wildcard='PDF files (*.pdf)|*.pdf',
						   style=wx.FD_SAVE|wx.FD_OVERWRITE_PROMPT,
						   defaultFile='保安基準適合検討表.pdf') as dlg:
			if dlg.ShowModal() != wx.ID_OK:
				return
			output_path = dlg.GetPath()
		
		try:
			data = self._collect_form_data()
			generate_form2_pdf(data, output_path)
			wx.MessageBox(f'PDFを保存しました:\n{output_path}', '完了', wx.ICON_INFORMATION)
		except Exception as e:
			wx.MessageBox(f'PDF生成エラー: {e}', 'エラー', wx.ICON_ERROR)
	
	def _collect_form_data(self) -> Form2Data:
		"""フォームからデータを収集"""
		data = Form2Data()
		data.length = self.length.GetValue()
		data.width = self.width.GetValue()
		data.height = self.height.GetValue()
		data.ground_clearance = self.ground_clearance.GetValue()
		data.chassis_structure = self.chassis_structure.GetValue()
		data.trailer_weight = self.trailer_weight.GetValue()
		data.coupler_type = self.coupler_type.GetValue()
		data.vehicle_weight = self.vehicle_weight.GetValue()
		data.axle_weight_front = self.axle_weight_front.GetValue()
		data.axle_weight_rear = self.axle_weight_rear.GetValue()
		data.tire_condition = self.tire_condition.GetValue()
		data.has_engine = self.has_engine.GetValue()
		data.fuel_system = self.fuel_system.GetValue()
		data.lubrication_system = self.lubrication_system.GetValue()
		data.exhaust_system = self.exhaust_system.GetValue()
		data.emission_control = self.emission_control.GetValue()
		data.parking_brake = self.parking_brake.GetValue()
		data.service_brake = self.service_brake.GetValue()
		data.suspension = self.suspension.GetValue()
		data.coupling_device = self.coupling_device.GetValue()
		data.safety_chain = self.safety_chain.GetValue()
		data.cargo_device = self.cargo_device.GetValue()
		data.frame_body = self.frame_body.GetValue()
		return data
	
	def _format_preview(self, data: Form2Data) -> str:
		"""プレビュー文字列を生成"""
		lines = [
			"=" * 60,
			"保安基準適合検討表（ライトトレーラ用）プレビュー",
			"=" * 60,
			"",
			"【2条: 寸法】",
			f"  長さ: {data.length} mm",
			f"  幅: {data.width} mm",
			f"  高さ: {data.height} mm",
			"",
			"【3条・3条の2】",
			f"  最低地上高: {data.ground_clearance} mm",
			f"  車台構造: {data.chassis_structure}",
			"",
			"【4条の2: 牽引】",
			f"  牽引重量: {data.trailer_weight} kg",
			f"  カプラー形式: {data.coupler_type}",
			"",
			"【5条: 重量等】",
			f"  車両重量: {data.vehicle_weight} kg",
			f"  前軸重: {data.axle_weight_front} kg",
			f"  後軸重: {data.axle_weight_rear} kg",
			"",
			"【6条〜11条の4】",
			f"  6条 タイヤ状態: {data.tire_condition}",
			f"  7条 原動機: {data.has_engine}",
			f"  8条 燃料装置: {data.fuel_system}",
			f"  9条 潤滑装置: {data.lubrication_system}",
			f"  10条 排気管: {data.exhaust_system}",
			f"  11条 排出ガス: {data.emission_control}",
			"",
			"【12条〜21条】",
			f"  12条 駐車ブレーキ: {data.parking_brake}",
			f"  12条 常用ブレーキ: {data.service_brake}",
			f"  13条 緩衝装置: {data.suspension}",
			f"  17条 連結装置: {data.coupling_device}",
			f"  17条の2 安全装置: {data.safety_chain}",
			f"  20条 積載装置: {data.cargo_device}",
			f"  21条 車枠車体: {data.frame_body}",
			"",
			"=" * 60,
		]
		return "\n".join(lines)
	
	def _get_main_frame(self):
		"""MainFrameを取得"""
		parent = self.GetParent()
		while parent:
			if isinstance(parent, MainFrame):
				return parent
			parent = parent.GetParent()
		return None
	
	def get_state(self) -> dict:
		"""状態を保存"""
		return {
			'length': self.length.GetValue(),
			'width': self.width.GetValue(),
			'height': self.height.GetValue(),
			'ground_clearance': self.ground_clearance.GetValue(),
			'chassis_structure': self.chassis_structure.GetValue(),
			'trailer_weight': self.trailer_weight.GetValue(),
			'coupler_type': self.coupler_type.GetValue(),
			'vehicle_weight': self.vehicle_weight.GetValue(),
			'axle_weight_front': self.axle_weight_front.GetValue(),
			'axle_weight_rear': self.axle_weight_rear.GetValue(),
			'tire_condition': self.tire_condition.GetValue(),
			'has_engine': self.has_engine.GetValue(),
			'fuel_system': self.fuel_system.GetValue(),
			'lubrication_system': self.lubrication_system.GetValue(),
			'exhaust_system': self.exhaust_system.GetValue(),
			'emission_control': self.emission_control.GetValue(),
			'parking_brake': self.parking_brake.GetValue(),
			'service_brake': self.service_brake.GetValue(),
			'suspension': self.suspension.GetValue(),
			'coupling_device': self.coupling_device.GetValue(),
			'safety_chain': self.safety_chain.GetValue(),
			'cargo_device': self.cargo_device.GetValue(),
			'frame_body': self.frame_body.GetValue(),
		}
	
	def set_state(self, state):
		"""状態を復元"""
		if 'length' in state:
			self.length.SetValue(state['length'])
		if 'width' in state:
			self.width.SetValue(state['width'])
		if 'height' in state:
			self.height.SetValue(state['height'])
		if 'ground_clearance' in state:
			self.ground_clearance.SetValue(state['ground_clearance'])
		if 'chassis_structure' in state:
			self.chassis_structure.SetValue(state['chassis_structure'])
		if 'trailer_weight' in state:
			self.trailer_weight.SetValue(state['trailer_weight'])
		if 'coupler_type' in state:
			self.coupler_type.SetValue(state['coupler_type'])
		if 'vehicle_weight' in state:
			self.vehicle_weight.SetValue(state['vehicle_weight'])
		if 'axle_weight_front' in state:
			self.axle_weight_front.SetValue(state['axle_weight_front'])
		if 'axle_weight_rear' in state:
			self.axle_weight_rear.SetValue(state['axle_weight_rear'])
		if 'tire_condition' in state:
			self.tire_condition.SetValue(state['tire_condition'])
		if 'has_engine' in state:
			self.has_engine.SetValue(state['has_engine'])
		if 'fuel_system' in state:
			self.fuel_system.SetValue(state['fuel_system'])
		if 'lubrication_system' in state:
			self.lubrication_system.SetValue(state['lubrication_system'])
		if 'exhaust_system' in state:
			self.exhaust_system.SetValue(state['exhaust_system'])
		if 'emission_control' in state:
			self.emission_control.SetValue(state['emission_control'])
		if 'parking_brake' in state:
			self.parking_brake.SetValue(state['parking_brake'])
		if 'service_brake' in state:
			self.service_brake.SetValue(state['service_brake'])
		if 'suspension' in state:
			self.suspension.SetValue(state['suspension'])
		if 'coupling_device' in state:
			self.coupling_device.SetValue(state['coupling_device'])
		if 'safety_chain' in state:
			self.safety_chain.SetValue(state['safety_chain'])
		if 'cargo_device' in state:
			self.cargo_device.SetValue(state['cargo_device'])
		if 'frame_body' in state:
			self.frame_body.SetValue(state['frame_body'])


class VehicleFrameStrengthPanel(wx.Panel):
	"""車枠強度計算書
	トレーラーフレーム（シャーシ）の強度計算。
	複数セクション対応により、異なる断面構成を持つトレーラーに対応。
	各セクションで複数の支柱（梁）を並列配置、点荷重による曲げモーメント・応力を計算。
	"""
	def __init__(self, parent):
		super().__init__(parent)
		self.last = None
		v = wx.BoxSizer(wx.VERTICAL)

		t = wx.StaticText(self, label='車枠強度計算（新）')
		f = t.GetFont(); f.PointSize += 2; f = f.Bold(); t.SetFont(f)
		v.Add(t, 0, wx.ALL, 6)

		# 説明
		desc = wx.StaticText(self, label='トレーラーフレーム（シャーシ）の複雑な構造に対応した強度計算です。\n複数セクションを用いて、支柱の配置・断面が異なる設計に対応します。\n「全長L」はフレームの前後方向の全長です。')
		desc.SetForegroundColour(wx.Colour(60, 60, 60))
		v.Add(desc, 0, wx.ALL, 6)

		# 基本入力（寸法）
		grid_dim = wx.FlexGridSizer(0, 4, 8, 12)
		
		# 全長
		self.L = self._add_with_hint(grid_dim, 
			'全長 L [mm]', 
			'トレーラーフレームの前後方向の全長（カプラー〜リアまで）\n標準例：6711mm (内部) / 6794mm (外部)', 
			'6711')
		
		# 断面幅
		self.B = self._add_with_hint(grid_dim, 
			'断面幅 B [mm]', 
			'フレーム梁の左右方向の幅（横方向の寸法）', 
			'200')
		
		# 断面高さ
		self.H = self._add_with_hint(grid_dim, 
			'断面高さ H [mm]', 
			'フレーム梁の上下方向の高さ（縦方向の寸法）', 
			'100')

		# 角形鋼の板厚（矩形鋼の場合に使用）
		self.t_rect = self._add_with_hint(grid_dim,
			'板厚 t [mm]',
			'角形鋼の板厚（t>0で中空断面として計算）',
			'0')

		# メインの縦梁本数
		self.main_vertical_beams = self._add_with_hint(grid_dim,
			'メイン縦梁本数',
			'フレーム全体で使用するメイン縦梁の本数（複数セクション時のデフォルト値）',
			'2')

		grid_dim.AddGrowableCol(1,1); grid_dim.AddGrowableCol(3,1)
		box_dim = wx.StaticBoxSizer(wx.StaticBox(self, label='1. フレーム寸法'), wx.VERTICAL)
		box_dim.Add(grid_dim, 0, wx.EXPAND | wx.ALL, 6)

		# 断面タイプ選択（角形鋼／H形鋼）と追加寸法
		sec_box = wx.StaticBoxSizer(wx.StaticBox(self, label='断面タイプ'), wx.VERTICAL)
		row_type = wx.BoxSizer(wx.HORIZONTAL)
		row_type.Add(wx.StaticText(self, label='断面タイプ'), 0, wx.ALIGN_CENTER_VERTICAL|wx.RIGHT, 6)
		self.section_type = wx.Choice(self)
		self.section_type.Append('角形鋼（矩形断面）')
		self.section_type.Append('H形鋼')
		self.section_type.Append('複数セクション')
		self.section_type.SetSelection(2)  # デフォルトを「複数セクション」に変更
		row_type.Add(self.section_type, 0)
		sec_box.Add(row_type, 0, wx.ALL, 4)

		# H形鋼寸法入力
		grid_h = wx.FlexGridSizer(0, 4, 6, 12)
		self.H_tot = self._add_with_hint(grid_h, 'H形鋼 全高 H [mm]', '断面の上下方向の全高（フランジ外々）', '100')
		self.bf = self._add_with_hint(grid_h, 'フランジ幅 bf [mm]', '左右方向のフランジの幅', '100')
		self.tf = self._add_with_hint(grid_h, 'フランジ厚 tf [mm]', '上下フランジの板厚', '9')
		self.tw = self._add_with_hint(grid_h, 'ウェブ厚 tw [mm]', '中央ウェブの板厚', '6')
		grid_h.AddGrowableCol(1,1); grid_h.AddGrowableCol(3,1)
		sec_box.Add(grid_h, 0, wx.EXPAND|wx.ALL, 4)

		# 複数セクション用パネル
		self.multi_section_panel = wx.Panel(self)
		multi_sizer = wx.BoxSizer(wx.VERTICAL)
		desc_multi = wx.StaticText(self.multi_section_panel, label=
			'トレーラーフレームを複数の構造セクションに分割して定義します。\n'
			'各セクションにおいて、位置範囲・梁構成・断面寸法を指定してください。\n'
			'・位置：フレーム前端からの距離(mm)\n'
			'・縦梁本数：前後方向に配置される支柱の本数（複数梁の並列配置に対応）\n'
			'・横梁本数：左右方向に配置される梁の本数（梁間を支持する部材。縦梁間の距離に影響）\n'
			'・B×H×t：各支柱の断面寸法(mm) - t=0で実心、t>0で中空断面')
		desc_multi.SetForegroundColour(wx.Colour(60, 60, 60))
		f_desc = desc_multi.GetFont(); f_desc.PointSize -= 1; desc_multi.SetFont(f_desc)
		multi_sizer.Add(desc_multi, 0, wx.ALL, 4)

		self.sections_grid = wx.grid.Grid(self.multi_section_panel)
		self.sections_grid.CreateGrid(5, 7)
		self.sections_grid.SetColLabelValue(0, '開始位置 x1 [mm]')
		self.sections_grid.SetColLabelValue(1, '終了位置 x2 [mm]')
		self.sections_grid.SetColLabelValue(2, '縦梁本数')
		self.sections_grid.SetColLabelValue(3, '横梁本数')
		self.sections_grid.SetColLabelValue(4, '幅 B [mm]')
		self.sections_grid.SetColLabelValue(5, '高さ H [mm]')
		self.sections_grid.SetColLabelValue(6, '板厚 t [mm]')
		for c in range(7):
			self.sections_grid.SetColSize(c, 95)
		
		# サンプルデータ（図面例）
		# 縦梁本数はメイン縦梁本数欄から取得、デフォルトは2
		self._initial_sample_data = [
			('0', '3050', '3', '150', '100', '4.5'),
			('3050', '4120', '2', '150', '100', '4.5'),
			('4120', '6711', '3', '150', '100', '4.5'),
		]
		for idx, (x1, x2, nbeams_h, b, h, t) in enumerate(self._initial_sample_data):
			if idx < self.sections_grid.GetNumberRows():
				self.sections_grid.SetCellValue(idx, 0, x1)
				self.sections_grid.SetCellValue(idx, 1, x2)
				self.sections_grid.SetCellValue(idx, 2, '2')  # デフォルトは2本
				self.sections_grid.SetCellValue(idx, 3, nbeams_h)
				self.sections_grid.SetCellValue(idx, 4, b)
				self.sections_grid.SetCellValue(idx, 5, h)
				self.sections_grid.SetCellValue(idx, 6, t)
		
		multi_sizer.Add(self.sections_grid, 1, wx.EXPAND|wx.ALL, 4)
		self.multi_section_panel.SetSizer(multi_sizer)
		self.multi_section_panel.Hide()
		sec_box.Add(self.multi_section_panel, 1, wx.EXPAND|wx.ALL, 4)

		box_dim.Add(sec_box, 0, wx.EXPAND | wx.ALL, 6)
		v.Add(box_dim, 0, wx.EXPAND | wx.ALL, 6)

		# 初期は角形鋼のみ有効
		self._update_section_type()
		self.section_type.Bind(wx.EVT_CHOICE, lambda e: (self._update_section_type(), e.Skip()))
		# メイン縦梁本数の変更時に各セクションに反映
		self.main_vertical_beams.Bind(wx.EVT_TEXT, self._on_main_beams_change)

		# 基本入力（材料）
		grid_mat = wx.FlexGridSizer(0, 4, 8, 12)
		# 材質選択
		grid_mat.Add(wx.StaticText(self, label='材質'), 0, wx.ALIGN_CENTER_VERTICAL)
		self.material_choice = wx.Choice(self)
		self.material_names = ['SS400', 'S355', 'S235', 'カスタム']
		for n in self.material_names:
			self.material_choice.Append(n)
		self.material_choice.SetSelection(0)
		grid_mat.Add(self.material_choice, 0, wx.EXPAND)
		grid_mat.Add(wx.StaticText(self), 0)
		grid_mat.Add(wx.StaticText(self), 0)
		self.tensile = self._add_with_hint(grid_mat, 
			'引張強さ [N/mm²]', 
			'フレーム材料の最大引張応力（例：SS400=235, S400=355等）', 
			'355')
		self.yield_pt = self._add_with_hint(grid_mat, 
			'降伏点 [N/mm²]', 
			'フレーム材料の降伏応力（弾性限界）', 
			'365')
		self.factor = self._add_with_hint(grid_mat, 
			'荷重倍率', 
			'安全性評価時の動的荷重倍数（通常2.5等）', 
			'2.5')

		grid_mat.AddGrowableCol(1,1); grid_mat.AddGrowableCol(3,1)
		box_mat = wx.StaticBoxSizer(wx.StaticBox(self, label='2. 材料強度'), wx.VERTICAL)
		box_mat.Add(grid_mat, 0, wx.EXPAND | wx.ALL, 6)
		v.Add(box_mat, 0, wx.EXPAND | wx.ALL, 6)

		# 材質プリセット（N/mm²）
		self.material_presets = {
			'SS400': {'yield': 245.0, 'tensile': 400.0},
			'S355': {'yield': 355.0, 'tensile': 470.0},
			'S235': {'yield': 235.0, 'tensile': 360.0},
		}
		self.material_choice.Bind(wx.EVT_CHOICE, lambda e: (self._update_material(), e.Skip()))
		self._update_material()

		# 荷重リストセクションのタイトル
		t_load = wx.StaticText(self, label='3. 荷重リスト（点荷重）')
		f_load = t_load.GetFont(); f_load.PointSize += 1; t_load.SetFont(f_load)
		v.Add(t_load, 0, wx.LEFT|wx.TOP, 6)

		# 説明文
		desc_load = wx.StaticText(self, label=
			'フレーム上に作用する荷重を点荷重で入力します。\n'
			'・名称: 部品名等（例）エンジン、サスペンション、ペイロード等\n'
			'・重量: kg 単位で入力してください。\n'
			'・位置: フレーム前端から後方へ向かって、mm 単位で計測した位置。')
		desc_load.SetForegroundColour(wx.Colour(60, 60, 60))
		f_desc = desc_load.GetFont(); f_desc.PointSize -= 1; desc_load.SetFont(f_desc)
		v.Add(desc_load, 0, wx.LEFT|wx.RIGHT|wx.TOP|wx.BOTTOM, 12)

		# グリッド
		hl = wx.BoxSizer(wx.HORIZONTAL)
		self.load_grid = wx.grid.Grid(self)
		self.load_grid.CreateGrid(4, 3)
		self.load_grid.SetColLabelValue(0, '名称（部品）')
		self.load_grid.SetColLabelValue(1, '重量 [kg]')
		self.load_grid.SetColLabelValue(2, '位置 [mm]')
		self.load_grid.AutoSizeColumns()
		hl.Add(self.load_grid, 1, wx.EXPAND|wx.ALL, 4)

		# 行追加・削除ボタン
		ctrls = wx.BoxSizer(wx.VERTICAL)
		btn_add = wx.Button(self, label='行追加')
		btn_remove = wx.Button(self, label='行削除')
		btn_import = wx.Button(self, label='部品表から転用')
		btn_add.SetToolTip('新しい行を追加して、荷重を追加入力できます。')
		btn_remove.SetToolTip('選択した行を削除します。\n選択なしの場合は最後の行を削除します。')
		btn_import.SetToolTip('重量計算パネルの部品表データを\n荷重リストに自動転用します。')
		ctrls.Add(btn_add, 0, wx.BOTTOM, 4)
		ctrls.Add(btn_remove, 0, wx.BOTTOM, 4)
		ctrls.Add(btn_import, 0)
		hl.Add(ctrls, 0, wx.ALIGN_TOP|wx.ALL, 4)
		v.Add(hl, 1, wx.EXPAND|wx.ALL, 6)

		# 面荷重（スプリングハンガ等）
		dist_box = wx.StaticBoxSizer(wx.StaticBox(self, label='4. 面荷重/面支持（スプリングハンガ等：区間一様分布）'), wx.VERTICAL)
		desc_dist = wx.StaticText(self, label='ハンガ本数に応じて任意行を追加してください。\n・中心位置と接触面積(mm²)を入力すると、自動的に区間として計算されます\n・面荷重: 下向きの一様荷重として扱います\n・面支持: 上向きの一様反力として扱います（接触面積に応じて剛性補正）')
		desc_dist.SetForegroundColour(wx.Colour(60, 60, 60))
		dist_box.Add(desc_dist, 0, wx.ALL, 4)
		self.dist_load_grid = wx.grid.Grid(self)
		self.dist_load_grid.CreateGrid(3, 5)
		self.dist_load_grid.SetColLabelValue(0, '名称')
		self.dist_load_grid.SetColLabelValue(1, '重量/反力 [kg]')
		self.dist_load_grid.SetColLabelValue(2, 'カプラーからハンガー中心位置までの距離 [mm]')
		self.dist_load_grid.SetColLabelValue(3, '接触面積 [mm²]')
		self.dist_load_grid.SetColLabelValue(4, '種別')
		self.dist_load_grid.AutoSizeColumns()
		# 種別列にドロップダウンリストを設定
		from wx.grid import GridCellChoiceEditor
		for r in range(self.dist_load_grid.GetNumberRows()):
			attr = wx.grid.GridCellAttr()
			attr.SetEditor(GridCellChoiceEditor(['面荷重', '面支持'], allowOthers=False))
			attr.SetAlignment(wx.ALIGN_CENTER, wx.ALIGN_CENTER)
			self.dist_load_grid.SetAttr(r, 4, attr)
			self.dist_load_grid.SetCellValue(r, 4, '面支持')  # デフォルト値を「面支持」に
		dist_box.Add(self.dist_load_grid, 1, wx.EXPAND|wx.ALL, 4)

		# 面支持剛性係数 α 入力（接触面積によるZ倍率の係数）
		alpha_row = wx.BoxSizer(wx.HORIZONTAL)
		alpha_row.Add(wx.StaticText(self, label='面支持剛性係数 α'), 0, wx.ALIGN_CENTER_VERTICAL|wx.RIGHT, 8)
		self.support_area_alpha = wx.TextCtrl(self, value='1.0', style=wx.TE_RIGHT)
		self.support_area_alpha.SetToolTip('面支持区間のモーメントを「1 - α × (面積/500)」で低減します（最小0.1）。10mm²刻みでも安全率が変動します。')
		alpha_row.Add(self.support_area_alpha, 0)
		dist_box.Add(alpha_row, 0, wx.ALL, 4)
		dist_ctrls = wx.BoxSizer(wx.HORIZONTAL)
		btn_dist_add = wx.Button(self, label='面荷重 行追加')
		btn_dist_remove = wx.Button(self, label='面荷重 行削除')
		dist_ctrls.Add(btn_dist_add, 0, wx.RIGHT, 4)
		dist_ctrls.Add(btn_dist_remove, 0)
		dist_box.Add(dist_ctrls, 0, wx.ALIGN_LEFT|wx.ALL, 4)
		v.Add(dist_box, 0, wx.EXPAND|wx.ALL, 6)

		# 計算・PDFボタン
		row = wx.BoxSizer(wx.HORIZONTAL)
		btn_calc = wx.Button(self, label='計算')
		btn_pdf = wx.Button(self, label='PDF出力')
		btn_pdf.Enable(False)
		row.Add(btn_calc, 0, wx.RIGHT, 8)
		row.Add(btn_pdf, 0)
		v.Add(row, 0, wx.ALIGN_CENTER | wx.ALL, 6)
		self.btn_pdf = btn_pdf

		self.result_text = wx.TextCtrl(self, style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_WORDWRAP)
		v.Add(self.result_text, 1, wx.EXPAND | wx.ALL, 6)

		# イベント
		btn_add.Bind(wx.EVT_BUTTON, lambda e: self.load_grid.AppendRows(1))
		btn_remove.Bind(wx.EVT_BUTTON, lambda e: self._remove_selected_rows())
		btn_import.Bind(wx.EVT_BUTTON, lambda e: self._import_from_components())
		btn_dist_add.Bind(wx.EVT_BUTTON, lambda e: self._add_dist_row())
		btn_dist_remove.Bind(wx.EVT_BUTTON, lambda e: self._remove_selected_dist_rows())
		btn_calc.Bind(wx.EVT_BUTTON, lambda e: (self.on_calc(), e.Skip()))
		btn_pdf.Bind(wx.EVT_BUTTON, lambda e: (self.on_export_pdf(), e.Skip()))

		self.SetSizer(v)

	def _add_dist_row(self):
		"""面荷重グリッドに行を追加し、ドロップダウンを設定"""
		from wx.grid import GridCellChoiceEditor
		self.dist_load_grid.AppendRows(1)
		r = self.dist_load_grid.GetNumberRows() - 1
		# 新しい行にドロップダウン属性を設定
		attr = wx.grid.GridCellAttr()
		attr.SetEditor(GridCellChoiceEditor(['面荷重', '面支持'], allowOthers=False))
		attr.SetAlignment(wx.ALIGN_CENTER, wx.ALIGN_CENTER)
		self.dist_load_grid.SetAttr(r, 4, attr)
		self.dist_load_grid.SetCellValue(r, 4, '面支持')  # デフォルト値

	def _remove_selected_rows(self):
		rows = self.load_grid.GetSelectedRows()
		if not rows:
			# remove last row
			self.load_grid.DeleteRows(self.load_grid.GetNumberRows()-1)
			return
		for r in sorted(rows, reverse=True):
			self.load_grid.DeleteRows(r)

	def _remove_selected_dist_rows(self):
		rows = self.dist_load_grid.GetSelectedRows()
		if not rows:
			# remove last row
			if self.dist_load_grid.GetNumberRows() > 0:
				self.dist_load_grid.DeleteRows(self.dist_load_grid.GetNumberRows()-1)
			return
		for r in sorted(rows, reverse=True):
			self.dist_load_grid.DeleteRows(r)


	def _import_from_components(self):
		"""重量計算パネルの部品表から荷重リストに転用"""
		try:
			# MainFrame および重量計算パネルへアクセス
			main_frame = self._get_main_frame()
			if not main_frame or not main_frame.weight_panel:
				wx.MessageBox('重量計算パネルにアクセスできません。', 'エラー', wx.OK | wx.ICON_ERROR)
				return
			
			# 部品表グリッドから部品データを抽出
			weight_panel = main_frame.weight_panel
			components_grid = weight_panel.components_grid
			
			# 既存の荷重リストをクリア
			if self.load_grid.GetNumberRows() > 0:
				self.load_grid.DeleteRows(0, self.load_grid.GetNumberRows())
			
			# グリッドから部品データを読み込み
			for row in range(components_grid.GetNumberRows()):
				name = components_grid.GetCellValue(row, 1)  # 名称
				weight = components_grid.GetCellValue(row, 2)  # 重量 Wi
				position = components_grid.GetCellValue(row, 3)  # 位置 Li
				
				# 名称か重量が入力されていれば転用
				if name or weight:
					self.load_grid.AppendRows(1)
					r = self.load_grid.GetNumberRows() - 1
					self.load_grid.SetCellValue(r, 0, name)
					self.load_grid.SetCellValue(r, 1, weight)
					self.load_grid.SetCellValue(r, 2, position)
			
			if self.load_grid.GetNumberRows() == 0:
				wx.MessageBox('部品表に有効なデータがありません。', '情報', wx.OK | wx.ICON_INFORMATION)
			else:
				wx.MessageBox(f'{self.load_grid.GetNumberRows()}件の部品データを転用しました。', '完了', wx.OK | wx.ICON_INFORMATION)
		
		except Exception as e:
			wx.MessageBox(f'転用中にエラーが発生しました:\n{e}', 'エラー', wx.OK | wx.ICON_ERROR)

	def _get_main_frame(self):
		"""MainFrameを取得"""
		parent = self.GetParent()
		while parent:
			if isinstance(parent, MainFrame):
				return parent
			parent = parent.GetParent()
		return None

	def _add(self, sizer, label, default='', hint=''):
		t = wx.TextCtrl(self, value=default, style=wx.TE_RIGHT)
		if hint:
			t.SetHint(hint)
		sizer.Add(wx.StaticText(self, label=label), 0, wx.ALIGN_CENTER_VERTICAL)
		sizer.Add(t, 0, wx.EXPAND)
		return t

	def _add_with_hint(self, sizer, label, description, default=''):
		"""入力フィールド＋説明テキストを追加"""
		t = wx.TextCtrl(self, value=default, style=wx.TE_RIGHT)
		sizer.Add(wx.StaticText(self, label=label), 0, wx.ALIGN_CENTER_VERTICAL)
		sizer.Add(t, 0, wx.EXPAND)
		# 説明文を追加（小さいフォントで）
		desc = wx.StaticText(self, label=f'  → {description}')
		desc.SetForegroundColour(wx.Colour(100, 100, 100))
		f = desc.GetFont(); f.PointSize -= 1; desc.SetFont(f)
		sizer.Add(desc, 0, wx.ALIGN_CENTER_VERTICAL, 0)
		sizer.Add(wx.StaticText(self, label=''), 0)  # spacer
		return t

	def _update_material(self):
		"""材質選択に応じて強度欄の値と有効/無効を切替"""
		name = self.material_choice.GetString(self.material_choice.GetSelection()) if hasattr(self, 'material_choice') else 'カスタム'
		preset = self.material_presets.get(name)
		if preset:
			self.tensile.SetValue(f"{preset['tensile']:.0f}")
			self.yield_pt.SetValue(f"{preset['yield']:.0f}")
			self.tensile.Enable(False)
			self.yield_pt.Enable(False)
		else:
			self.tensile.Enable(True)
			self.yield_pt.Enable(True)

	def _on_main_beams_change(self, event):
		"""メインの縦梁本数が変更された時に、各セクションの縦梁本数を更新"""
		try:
			main_beams = int(float(self.main_vertical_beams.GetValue() or 2))
			if main_beams > 0 and hasattr(self, 'sections_grid'):
				for row in range(self.sections_grid.GetNumberRows()):
					# 既存の値がある場合は上書きしない（ユーザーがカスタマイズしている可能性）
					current_val = self.sections_grid.GetCellValue(row, 2)
					if not current_val or current_val.strip() == '':
						self.sections_grid.SetCellValue(row, 2, str(main_beams))
		except Exception:
			pass
		event.Skip()

	def _update_section_type(self):
		"""断面タイプに応じて入力有効/無効を切替"""
		selection = self.section_type.GetSelection() if hasattr(self, 'section_type') else 0
		is_rect = (selection == 0)
		is_hbeam = (selection == 1)
		is_multi = (selection == 2)
		
		# 角形鋼: B,H を有効
		self.B.Enable(is_rect)
		self.H.Enable(is_rect)
		self.t_rect.Enable(is_rect)
		
		# H形鋼寸法
		for ctrl in [getattr(self, n, None) for n in ('H_tot','bf','tf','tw')]:
			if ctrl:
				ctrl.Enable(is_hbeam)
		
		# 複数セクションパネル
		if hasattr(self, 'multi_section_panel'):
			if is_multi:
				self.multi_section_panel.Show()
			else:
				self.multi_section_panel.Hide()
			self.GetParent().Layout()

	def on_calc(self):
		try:
			L = float(self.L.GetValue() or 0)
			# 断面タイプ取得
			section_type_idx = self.section_type.GetSelection() if hasattr(self, 'section_type') else 0
			is_rect = (section_type_idx == 0)
			is_hbeam = (section_type_idx == 1)
			is_multi = (section_type_idx == 2)
			
			bf = 0.0; tf = 0.0; tw = 0.0; B = 0.0; H = 0.0; t = 0.0
			
			if is_rect:
				B = float(self.B.GetValue() or 0)
				H = float(self.H.GetValue() or 0)
				t = float(self.t_rect.GetValue() or 0)
			elif is_hbeam:
				H = float(self.H_tot.GetValue() or 0)
				bf = float(self.bf.GetValue() or 0)
				tf = float(self.tf.GetValue() or 0)
				tw = float(self.tw.GetValue() or 0)
			
			tensile = float(self.tensile.GetValue() or 0)
			yield_pt = float(self.yield_pt.GetValue() or 0)
			factor = float(self.factor.GetValue() or 1)

			# read loads
			loads = []
			for r in range(self.load_grid.GetNumberRows()):
				name = self.load_grid.GetCellValue(r,0) or f'P{r+1}'
				try:
					w = float(self.load_grid.GetCellValue(r,1) or 0)
				except Exception:
					w = 0.0
				try:
					x = float(self.load_grid.GetCellValue(r,2) or 0)
				except Exception:
					x = 0.0
				if w != 0:
					loads.append((name, w, x))

				# read distributed loads (uniform over start-end)
				dist_loads = []  # (name, weight, x1, x2, kind, area_mm2)
			dist_debug_info = []  # デバッグ用
			for r in range(self.dist_load_grid.GetNumberRows()):
				name = self.dist_load_grid.GetCellValue(r,0) or f'Q{r+1}'
				try:
					w = float(self.dist_load_grid.GetCellValue(r,1) or 0)
				except Exception:
					w = 0.0
				try:
					center_pos = float(self.dist_load_grid.GetCellValue(r,2) or 0)
				except Exception:
					center_pos = 0.0
				try:
					area_mm2 = float(self.dist_load_grid.GetCellValue(r,3) or 0)
				except Exception:
					area_mm2 = 0.0
				# 種別を取得
				kind = (self.dist_load_grid.GetCellValue(r,4) or '面荷重').strip()
				is_support = (kind == '面支持' or kind.lower() in ('支持','support'))
				# デバッグ情報を記録
				raw_w = self.dist_load_grid.GetCellValue(r,1)
				raw_area = self.dist_load_grid.GetCellValue(r,3)
				dist_debug_info.append(f'    行{r+1}: name={name}, w_raw={raw_w}, w={w}, area_raw={raw_area}, area={area_mm2}, kind={kind}')
				# 中心位置と面積から開始・終了位置を計算
				if area_mm2 > 0:
					import math
					width = math.sqrt(area_mm2)  # 面積の平方根を幅とする
					x1 = center_pos - width / 2.0
					x2 = center_pos + width / 2.0
					# 荷重としては w!=0 の場合だけせん断力に反映する
					if w != 0:
						dist_loads.append((name, w, x1, x2, kind, area_mm2))
					# 面支持は w=0 でもモーメント低減のために登録しておく
					elif is_support:
						dist_loads.append((name, 0.0, x1, x2, kind, area_mm2))
				else:
					dist_debug_info[-1] += ' (※スキップ: 面積0)'
			npts = 121
			xs = [i*(L/(npts-1)) for i in range(npts)]
			Vs = [0.0]*npts
			for name,w,x in loads:
				for i,xx in enumerate(xs):
					if xx >= x:
						Vs[i] -= w*9.80665
			# 面荷重/面支持（区間一様荷重/反力）をせん断力へ加算
			for name,w,x1,x2,kind,area_cm2 in dist_loads:
				length = x2 - x1
				if length <= 0:
					continue
				q = (w*9.80665) / length  # N/mm 一様量
				is_support = (kind == '面支持' or kind.lower() in ('支持','support'))
				for i,xx in enumerate(xs):
					if xx < x1:
						continue
					if xx >= x2:
						Vs[i] += q * length if is_support else - q * length
					else:
						Vs[i] += q * (xx - x1) if is_support else - q * (xx - x1)

			# integrate for moment (M[0]=0)
			Ms = [0.0]*npts
			for i in range(1,npts):
				dx = xs[i]-xs[i-1]
				Ms[i] = Ms[i-1] + 0.5*(Vs[i]+Vs[i-1])*dx

			# 複数セクション対応：各位置でのZ値を計算
			Zs = [0.0]*npts
			# 面支持によるモーメント低減補正（荷重分散効果）を単独で使用
			# Z倍率は不要（モーメント低減で十分に効果が出る）
			M_multiplier = [1.0]*npts
			Z_multiplier = [1.0]*npts  # 互換性のために残す（使用しない）
			
			# 係数 α を入力から取得（不正値は既定 1.0）
			try:
				alpha_coeff = float(self.support_area_alpha.GetValue() or '1.0')
				if alpha_coeff < 0:
					alpha_coeff = 0.0
			except Exception:
				alpha_coeff = 1.0
			
			for name,w,x1,x2,kind,area_mm2 in dist_loads:
				if (kind == '面支持' or kind.lower() in ('支持','support')) and area_mm2 > 0 and x2 > x1:
					# モーメント低減係数: 接触面積が大きいほど低減（支持効果が強い）
					# さらに高感度化：M_factor = 1 - α × (面積/500)
					# α=1.0の場合：
					#   面積10mm² → 98%（2%低減）
					#   面積100mm² → 80%（20%低減）
					#   面積500mm² → 30%（70%低減、最小保持）
					#   面積1,000mm² → 10%（下限に到達）
					m_reduction = alpha_coeff * (area_mm2 / 500.0)  # 10mm²刻みでも変動を感じる超高感度
					m_factor = max(0.1, 1.0 - m_reduction)  # 最小10%は保持
					for i,xx in enumerate(xs):
						if x1 <= xx <= x2:
							M_multiplier[i] *= m_factor
			
			# モーメント値に低減補正を適用
			Ms = [Ms[i] * M_multiplier[i] for i in range(len(Ms))]
			
			section_results = []  # (x1, x2, I, Z, sigma_max)
			
			if is_multi:
				# セクション定義テーブルから読み込み
				for row in range(self.sections_grid.GetNumberRows()):
					try:
						x1 = float(self.sections_grid.GetCellValue(row, 0) or 0)
						x2 = float(self.sections_grid.GetCellValue(row, 1) or 0)
						nbeams_v = int(float(self.sections_grid.GetCellValue(row, 2) or 1))  # 縦梁本数
						nbeams_h = int(float(self.sections_grid.GetCellValue(row, 3) or 1))  # 横梁本数
						b = float(self.sections_grid.GetCellValue(row, 4) or 0)
						h = float(self.sections_grid.GetCellValue(row, 5) or 0)
						t_sec = float(self.sections_grid.GetCellValue(row, 6) or 0)
						
						if x1 < x2 and nbeams_v > 0:
							# 複数縦梁の複合梁として計算：有効断面係数 Z_eff = Z × nbeams_v
							if t_sec > 0 and b > 2*t_sec and h > 2*t_sec:
								b_in = b - 2.0*t_sec
								h_in = h - 2.0*t_sec
								I_one = (b * (h**3) - b_in * (h_in**3)) / 12.0
							else:
								I_one = (b * h**3) / 12.0
							Z_one = I_one / (h/2.0) if h > 0 else 0.0
							Z_eff = Z_one * nbeams_v  # 複数梁による有効Z値
							
							# 横梁の相互作用効果を適用
							# 横梁が多いほど、縦梁間の相対変位が減小される
							# 効果係数 = 1.0 + 0.15 * (横梁本数 - 1)
							# 横梁本数1: 係数1.0（効果なし）
							# 横梁本数2: 係数1.15
							# 横梁本数3: 係数1.30
							# 横梁本数4: 係数1.45
							horizontal_beam_factor = 1.0 + 0.15 * max(0, nbeams_h - 1)
							Z_eff_with_horiz = Z_eff * horizontal_beam_factor
							
							# このセクション内の位置のZs値を設定
							for i, xi in enumerate(xs):
								if x1 <= xi <= x2:
									Zs[i] = Z_eff_with_horiz  # Z_multiplierは使用しない
							
							# セクションの最大応力を計算（このセクション内のMs最大値を使用）
							Ms_in_sec = [Ms[i] for i in range(len(Ms)) if x1 <= xs[i] <= x2]
							if Ms_in_sec:
								Mmax_sec = max(Ms_in_sec, key=lambda v: abs(v))
								sigma_max_sec = abs(Mmax_sec) / Z_eff_with_horiz if Z_eff_with_horiz > 0 else 0.0
								section_results.append((x1, x2, I_one*nbeams_v, Z_eff_with_horiz, sigma_max_sec, nbeams_v, nbeams_h, horizontal_beam_factor))
					except Exception:
						pass
				
				# 全体の最大応力を計算（すべてのセクションを考慮）
				max_sigma = 0.0
				for i in range(len(Ms)):
					if Zs[i] > 0:
						sigma = abs(Ms[i]) / Zs[i]
						max_sigma = max(max_sigma, sigma)
				sigma_max = max_sigma
				Mmax = max(Ms, key=lambda v: abs(v))
				# 単一セクション結果は最大値で代表
				I = sum(s[2] for s in section_results) / len(section_results) if section_results else 0.0
				Z = sum(s[3] for s in section_results) / len(section_results) if section_results else 0.0
				section_str = f'複数セクション構造（{len(section_results)}セクション）'
			else:
				# 単一セクション（従来の計算）
				for i in range(npts):
					if is_rect:
						if t>0 and (B>2*t) and (H>2*t):
							b_in = B - 2.0*t
							h_in = H - 2.0*t
							I = (B * (H**3) - b_in * (h_in**3)) / 12.0
						else:
							I = (B * H**3) / 12.0
						Zs[i] = (I / (H/2.0) if H>0 else 0.0)  # Z_multiplierは使用しない
					else:
						# H形鋼
						h_web = max(H - 2*tf, 0)
						Iw = (tw * (h_web**3)) / 12.0
						Af = bf * tf
						d = H/2.0 - tf/2.0
						If_one = (bf * (tf**3))/12.0 + Af * (d**2)
						I = Iw + 2.0 * If_one
					Zs[i] = (I / (H/2.0) if H>0 else 0.0)  # Z_multiplierは使用しない
				Mmax = max(Ms, key=lambda v: abs(v))
				sigma_max = 0.0
				for i in range(len(Ms)):
					if Zs[i] > 0:
						sigma = abs(Ms[i]) / Zs[i]
						sigma_max = max(sigma_max, sigma)
				
				if is_rect:
					if t>0:
						section_str = f'角形鋼（中空） B×H = {B:.0f}×{H:.0f} mm, t={t:.1f} mm'
					else:
						section_str = f'角形鋼（矩形） B×H = {B:.0f}×{H:.0f} mm'
				else:
					section_str = f'H形鋼 H={H:.0f}, bf={bf:.0f}, tf={tf:.1f}, tw={tw:.1f} mm'
				Z = Zs[0] if Zs else 0.0  # 代表値
				section_results = []

			sf_break = tensile / (factor * sigma_max) if sigma_max>0 else 0.0
			sf_yield = yield_pt / (factor * sigma_max) if sigma_max>0 else 0.0

			# 材質名
			mat_name = self.material_choice.GetString(self.material_choice.GetSelection()) if hasattr(self, 'material_choice') else 'カスタム'
			self.last = {
				'L':L,'loads':loads,'xs':xs,'Vs':Vs,'Ms':Ms,'Zs':Zs,
				'I':I,'Z':Z,'Mmax':Mmax,'sigma_max':sigma_max,
				'sf_break':sf_break,'sf_yield':sf_yield,
				'factor':factor,'tensile':tensile,'yield_pt':yield_pt,
				'section_type': ('rect' if is_rect else 'hbeam' if is_hbeam else 'multi'),
				'section_str': section_str,
				'material': mat_name,
				'section_results': section_results,
				'is_multi': is_multi,
				'dist_loads': dist_loads,
				'support_area_alpha': alpha_coeff
			}

			# display
			# 面支持の効果を計算（参考値）
			support_info = []
			total_m_reduction_pct = 0.0
			m_multiplier_min = min(M_multiplier) if M_multiplier else 1.0
			m_multiplier_max = max(M_multiplier) if M_multiplier else 1.0
			for name,w,x1,x2,kind,area_mm2 in dist_loads:
				if (kind == '面支持' or kind.lower() in ('支持','support')) and area_mm2 > 0:
					m_reduction = alpha_coeff * (area_mm2 / 500.0)
					m_factor = max(0.1, 1.0 - m_reduction)
					reduction_pct = (1.0 - m_factor) * 100
					total_m_reduction_pct = max(total_m_reduction_pct, reduction_pct)
					support_info.append(f'  {name}: 面積{area_mm2:.0f}mm² → M低減{reduction_pct:.1f}%（係数{m_factor:.1%}）')
			
			lines = [
				'車枠強度計算（新）- トレーラーフレーム',
				f'全長 L = {L:.0f} mm',
				self.last['section_str'],
				'',
				'【計算結果】',
				f'最大曲げモーメント Mmax = {Mmax/1000:.3f} N·m ({Mmax:.0f} N·mm)',
				f'最大曲げ応力 σmax = {sigma_max:.3f} N/mm²',
				'',
				'【計算方法の要点】',
				'・面荷重は区間一様の下向き荷重として扱い、曲げ応力を増加させます。',
				'・面支持（スプリングハンガ等）は区間一様の上向き反力として扱い、曲げ応力を低減させます。',
				'・面支持区間では、接触面積に応じてモーメント値を低減（荷重分散効果）',
				f'・係数 α = {alpha_coeff:.6f}（M低減 = α × 面積/500、10mm²刻みで変動）',
				'',
				'【面支持の効果】',
			]
			if support_info:
				lines.extend(support_info)
				if total_m_reduction_pct > 0:
					lines.append(f'  → 総合M低減率: {total_m_reduction_pct:.1f}%, 係数最小/最大: {m_multiplier_min:.3f} / {m_multiplier_max:.3f}')
			else:
				lines.append('  (面支持なし - グリッドに入力があるか確認してください)')
				lines.append(f'【診断】')
				lines.append(f'  グリッド読み込み結果（全{self.dist_load_grid.GetNumberRows()}行）：')
				lines.extend(dist_debug_info)
				lines.append(f'  dist_loads件数={len(dist_loads)}, α={alpha_coeff}')
				lines.append(f'  M低減係数 最小/最大: {m_multiplier_min:.3f} / {m_multiplier_max:.3f}')
			
			lines.extend([
				'',
				'【材質】',
				f'{self.last["material"]} (引張強さ {tensile:.0f} N/mm², 降伏点 {yield_pt:.0f} N/mm²)',
				'',
				'【安全性】',
				f'破断安全率 = {sf_break:.2f}  (基準 1.6) {"✓ OK" if sf_break >= 1.6 else "✗ NG"}',
				f'降伏安全率 = {sf_yield:.2f}  (基準 1.3) {"✓ OK" if sf_yield >= 1.3 else "✗ NG"}'
			])
			
			# 複数セクション時の詳細表示
			if is_multi and section_results:
				lines.append('\n【セクション別応力】')
				for item in section_results:
					if len(item) == 8:  # 新しい形式：縦梁、横梁、効果係数を含む
						x1, x2, I_sec, Z_sec, sigma_sec, nbeams_v, nbeams_h, horiz_factor = item
						lines.append(f'  セクション {section_results.index(item)+1}: 位置 {x1:.0f}～{x2:.0f} mm')
						lines.append(f'    梁構成：縦梁 {nbeams_v}本, 横梁 {nbeams_h}本 (横梁効果係数 {horiz_factor:.2f})')
						lines.append(f'    有効断面係数 Z = {Z_sec:.1f} mm³, 最大応力 σ = {sigma_sec:.3f} N/mm²')
					else:  # 旧形式
						x1, x2, I_sec, Z_sec, sigma_sec = item
						lines.append(f'  セクション {section_results.index(item)+1}: 位置 {x1:.0f}～{x2:.0f} mm')
						lines.append(f'    有効断面係数 Z = {Z_sec:.1f} mm³, 最大応力 σ = {sigma_sec:.3f} N/mm²')
			
			# 安全性がNGの場合、改善案を提案
			if sf_break < 1.6 or sf_yield < 1.3:
				suggestions = self._generate_improvement_suggestions(
					sf_break, sf_yield, sigma_max, tensile, yield_pt, factor,
					is_multi, Z, B, H, t if is_rect else 0
				)
				if suggestions:
					lines.append('\n【改善案】')
					for suggestion in suggestions:
						lines.append(suggestion)
			
				self.result_text.SetValue('\n'.join(lines))
				self._update_pdf_button()

		except Exception as e:
			wx.MessageBox(f'計算エラー: {e}', 'エラー', wx.OK | wx.ICON_ERROR)
			self._update_pdf_button(force_disable=True)

	def _generate_improvement_suggestions(self, sf_break, sf_yield, sigma_max, tensile, yield_pt, factor, is_multi, Z, B, H, t):
		"""安全性がNGの場合の改善案を生成"""
		suggestions = []
		
		# 必要な安全率
		target_break = 1.6
		target_yield = 1.3
		
		# 応力軽減に必要な断面係数の倍数
		if sf_break < target_break and sf_break > 0:
			z_increase_break = (target_break / sf_break) - 1.0
			suggestions.append(f'◆ 破断安全率不足 (現在 {sf_break:.2f}, 必要 {target_break:.2f})')
			suggestions.append(f'  必要な断面係数増加: {z_increase_break*100:.1f}%')
		
		if sf_yield < target_yield and sf_yield > 0:
			z_increase_yield = (target_yield / sf_yield) - 1.0
			suggestions.append(f'◆ 降伏安全率不足 (現在 {sf_yield:.2f}, 必要 {target_yield:.2f})')
			suggestions.append(f'  必要な断面係数増加: {z_increase_yield*100:.1f}%')
		
		suggestions.append('')
		suggestions.append('【推奨される改善方法】')
		
		# 1) 材質変更
		suggestions.append('\n1. 材質の変更（最も効果的）')
		if sigma_max > 0:
			required_tensile_break = sigma_max * factor * target_break
			required_yield_yield = sigma_max * factor * target_yield
			required_strength = max(required_tensile_break, required_yield_yield)
			suggestions.append(f'  → 現在の応力 {sigma_max:.2f} N/mm² に対して')
			suggestions.append(f'    必要な引張強さ: 約 {required_tensile_break:.0f} N/mm²')
			suggestions.append(f'    必要な降伏点: 約 {required_yield_yield:.0f} N/mm²')
			if required_strength > 400:
				suggestions.append(f'    推奨: S355 (450 N/mm²) または同等以上の材質')
			elif required_strength > 360:
				suggestions.append(f'    推奨: SS400 (400 N/mm²) または S355')
		
		# 2) 断面寸法の変更
		if Z > 0:
			z_increase = max(
				(target_break / sf_break - 1.0) if sf_break > 0 else 0,
				(target_yield / sf_yield - 1.0) if sf_yield > 0 else 0
			)
			if z_increase > 0:
				new_Z = Z * (1.0 + z_increase)
				suggestions.append(f'\n2. 断面寸法の変更')
				suggestions.append(f'  → 現在の断面係数 Z = {Z:.1f} mm³')
				suggestions.append(f'    必要な断面係数: 約 {new_Z:.1f} mm³')
				
				# 角形鋼の場合
				if not is_multi:
					if H > 0:
						# B×H の比を保持してスケーリング
						scale_factor = (new_Z / Z) ** (1/3)  # 立方根でスケール
						new_H = H * scale_factor
						new_B = B * scale_factor if B > 0 else H * scale_factor
						suggestions.append(f'    推奨: B×H = {new_B:.0f}×{new_H:.0f} mm (現在 {B:.0f}×{H:.0f} mm)')
						suggestions.append(f'           または同等の断面係数を持つ断面')
				else:
					suggestions.append(f'    推奨: 各セクションの断面寸法を比例的に拡大')
					suggestions.append(f'         （倍率: 約 {(new_Z / Z) ** (1/3):.2f}倍）')
		
		# 3) 支柱本数の増加
		if is_multi:
			suggestions.append(f'\n3. 支柱本数の増加（複数セクション構造）')
			z_increase = max(
				(target_break / sf_break - 1.0) if sf_break > 0 else 0,
				(target_yield / sf_yield - 1.0) if sf_yield > 0 else 0
			)
			if z_increase > 0:
				beam_multiplier = 1.0 + z_increase
				suggestions.append(f'  → 現在の支柱本数を {beam_multiplier:.1f}倍に増加')
				suggestions.append(f'    例：2本 → 3本、3本 → 4本へ増加')
		
		# 4) 複合的な改善
		suggestions.append(f'\n4. 複合的な改善（最適な設計）')
		suggestions.append(f'  → 上記の方法を組み合わせることで、より経済的な設計が可能')
		suggestions.append(f'  → 材質変更（小）+ 断面拡大（中程度）+ 支柱増加（小）')
		suggestions.append(f'  → などのバランスの取れた改善')

		return suggestions

	def _update_pdf_button(self, force_disable: bool = False):
		if not hasattr(self, 'btn_pdf'):
			return
		enable = (not force_disable) and _REPORTLAB_AVAILABLE and (self.last is not None)
		self.btn_pdf.Enable(enable)
		
	def on_export_pdf(self):
		"""車枠強度（新）の計算結果をPDF出力"""
		if not self.last:
			wx.MessageBox('先に計算を実行してください。', '情報', wx.OK | wx.ICON_INFORMATION)
			return
		if not _REPORTLAB_AVAILABLE:
			wx.MessageBox('ReportLabが未インストールです。requirements.txtをインストールしてください。', 'PDF出力不可', wx.ICON_ERROR)
			return
		dlg = wx.FileDialog(self, 'PDF保存先を選択', wildcard='PDF files (*.pdf)|*.pdf', style=wx.FD_SAVE|wx.FD_OVERWRITE_PROMPT, defaultFile='車枠強度計算書（新）.pdf')
		if dlg.ShowModal() != wx.ID_OK:
			dlg.Destroy(); return
		path = dlg.GetPath(); dlg.Destroy()
		try:
			self._generate_frame_pdf(path)
			wx.MessageBox(f'PDF出力完了:\n{path}', '完了', wx.OK | wx.ICON_INFORMATION)
		except Exception as e:
			wx.MessageBox(f'PDF出力中にエラーが発生しました:\n{e}', 'エラー', wx.OK | wx.ICON_ERROR)

	def _generate_frame_pdf(self, path: str):
		"""添付フォームを参考にした簡易レイアウトでPDFを生成"""
		from reportlab.lib import colors
		from reportlab.platypus import Table, TableStyle
		c = _pdf_canvas.Canvas(path, pagesize=_A4)
		w, h = _A4
		font = 'Helvetica'
		last = self.last or {}
		L = last.get('L', 0)
		alpha_coeff = last.get('support_area_alpha', 0.0)
		material = last.get('material', 'カスタム')
		tensile = last.get('tensile', 0)
		yield_pt = last.get('yield_pt', 0)
		factor = last.get('factor', 1.0)
		sf_break = last.get('sf_break', 0.0)
		sf_yield = last.get('sf_yield', 0.0)
		sigma_max = last.get('sigma_max', 0.0)
		Mmax = last.get('Mmax', 0.0)
		section_str = last.get('section_str', '')
		loads = last.get('loads', []) or []
		dist_loads = last.get('dist_loads', []) or []
		xs = last.get('xs', []) or []
		Vs = last.get('Vs', []) or []
		Ms = last.get('Ms', []) or []
		# ==== Page 1: 基本情報・荷重 ==== 
		y = h - 40
		c.setFont(font + '-Bold', 16)
		c.drawCentredString(w/2, y, '車枠強度計算書（新）')
		y -= 30
		c.setFont(font, 10)
		c.drawString(60, y, f'計算条件: 荷重倍率 n = {factor:.2f}, 面支持係数 α = {alpha_coeff:.4f}')
		y -= 14
		c.drawString(60, y, f'フレーム全長 L = {L:.1f} mm / 断面: {section_str}')
		y -= 14
		c.drawString(60, y, f'材質: {material} (σb={tensile:.0f} N/mm², σy={yield_pt:.0f} N/mm²)')
		y -= 18
		# 荷重一覧
		c.setFont(font + '-Bold', 11)
		c.drawString(60, y, '【荷重一覧】')
		y -= 16
		load_rows = [['No', '名称', '重量[kg]', '位置[mm]', '接触面積[mm²]', '区間[mm]', '種別']]
		for idx,(name,weight,pos) in enumerate(loads,1):
			load_rows.append([f'P{idx}', str(name), f'{weight:.1f}', f'{pos:.1f}', '', '', '点荷重'])
		for idx,item in enumerate(dist_loads,1):
			if len(item) >= 6:
				name,weight,x1,x2,kind,area = item[:6]
			else:
				continue
			center = (x1 + x2)/2.0
			length = x2 - x1
			load_rows.append([f'Q{idx}', str(name), f'{weight:.1f}', f'{center:.1f}', f'{area:.1f}', f'{length:.1f}', str(kind)])
		load_table = Table(load_rows, colWidths=[28,100,70,70,85,70,60])
		load_table.setStyle(TableStyle([
			('FONT',(0,0),(-1,-1),font,9),
			('FONT',(0,0),(-1,0),font+'-Bold',9),
			('GRID',(0,0),(-1,-1),0.5,colors.black),
			('BACKGROUND',(0,0),(-1,0),colors.lightgrey),
			('ALIGN',(0,0),(-1,-1),'CENTER'),
			('VALIGN',(0,0),(-1,-1),'MIDDLE'),
		]))
		load_table.wrapOn(c,w,h)
		load_table.drawOn(c,60,y - len(load_rows)*18)
		y -= (len(load_rows)*18 + 16)
		# 結果概要
		c.setFont(font + '-Bold', 11)
		c.drawString(60, y, '【計算結果】')
		y -= 14
		c.setFont(font, 10)
		c.drawString(70, y, f'Mmax = {Mmax/1000:.3f} kN·m   σmax = {sigma_max:.3f} N/mm²')
		y -= 14
		c.drawString(70, y, f'破断安全率 = {sf_break:.2f}  (基準1.6)')
		y -= 14
		c.drawString(70, y, f'降伏安全率 = {sf_yield:.2f} (基準1.3)')
		y -= 18
		c.drawString(70, y, '※面支持は接触面積に応じてモーメント低減 (1 - α×面積/500, 下限0.1)')
		c.showPage()
		# ==== Page 2: せん断力・曲げモーメント抜粋 ====
		y = h - 40
		c.setFont(font + '-Bold', 14)
		c.drawCentredString(w/2, y, 'せん断力・曲げモーメント抜粋')
		y -= 24
		c.setFont(font, 9)
		c.drawString(60, y, '代表点でのせん断力VとモーメントMを抜粋表示（詳細はアプリ計算結果を参照）')
		y -= 14
		if xs and Vs and Ms:
			step = max(1, len(xs)//18)
			rows = [['No','位置x[mm]','V[N]','M[N·mm]','M[kN·m]']]
			for i in range(0,len(xs),step):
				rows.append([str(i+1), f'{xs[i]:.1f}', f'{Vs[i]:.1f}', f'{Ms[i]:.1f}', f'{Ms[i]/1000:.3f}'])
			data_table = Table(rows, colWidths=[28,80,90,110,80])
			data_table.setStyle(TableStyle([
				('FONT',(0,0),(-1,-1),font,8),
				('FONT',(0,0),(-1,0),font+'-Bold',8),
				('GRID',(0,0),(-1,-1),0.5,colors.black),
				('BACKGROUND',(0,0),(-1,0),colors.lightgrey),
				('ALIGN',(0,0),(-1,-1),'CENTER'),
				('VALIGN',(0,0),(-1,-1),'MIDDLE'),
			]))
			data_table.wrapOn(c,w,h)
			data_table.drawOn(c,60,y - len(rows)*14)
			y -= (len(rows)*14 + 20)
		else:
			c.drawString(60, y, '計算データが不足しているため表を表示できません。')
			y -= 16
		c.showPage()
		c.save()

	def get_state(self) -> dict:
		"""車枠強度パネルの状態を保存"""
		# グリッドのデータを取得
		load_rows = []
		for r in range(self.load_grid.GetNumberRows()):
			name = self.load_grid.GetCellValue(r, 0)
			weight = self.load_grid.GetCellValue(r, 1)
			position = self.load_grid.GetCellValue(r, 2)
			if name or weight or position:
				load_rows.append((name, weight, position))

		# 面荷重/面支持データを保存（新仕様）
		dist_rows = []
		for r in range(self.dist_load_grid.GetNumberRows()):
			row = []
			for c in range(self.dist_load_grid.GetNumberCols()):
				row.append(self.dist_load_grid.GetCellValue(r, c))
			# 何か入力がある行のみ保存
			if any(v for v in row):
				dist_rows.append(row)
		
		# セクションデータを保存
		section_rows = []
		if hasattr(self, 'sections_grid'):
			for r in range(self.sections_grid.GetNumberRows()):
				x1 = self.sections_grid.GetCellValue(r, 0)
				x2 = self.sections_grid.GetCellValue(r, 1)
				nbeams_v = self.sections_grid.GetCellValue(r, 2)
				nbeams_h = self.sections_grid.GetCellValue(r, 3)
				b = self.sections_grid.GetCellValue(r, 4)
				h = self.sections_grid.GetCellValue(r, 5)
				t = self.sections_grid.GetCellValue(r, 6)
				if x1 or x2 or nbeams_v or nbeams_h or b or h or t:
					section_rows.append((x1, x2, nbeams_v, nbeams_h, b, h, t))
		
		return {
			'L': self.L.GetValue(),
			'B': self.B.GetValue(),
			'H': self.H.GetValue(),
			't_rect': self.t_rect.GetValue(),
			'main_vertical_beams': self.main_vertical_beams.GetValue(),
			'section_type': self.section_type.GetSelection(),
			'H_tot': self.H_tot.GetValue(),
			'bf': self.bf.GetValue(),
			'tf': self.tf.GetValue(),
			'tw': self.tw.GetValue(),
			'material_choice': self.material_choice.GetSelection(),
			'tensile': self.tensile.GetValue(),
			'yield_pt': self.yield_pt.GetValue(),
			'factor': self.factor.GetValue(),
			'load_rows': load_rows,
			'section_rows': section_rows,
			'dist_rows': dist_rows,
			'support_area_alpha': self.support_area_alpha.GetValue() if hasattr(self, 'support_area_alpha') else '0.001',
		}
	
	def set_state(self, state: dict):
		"""車枠強度パネルの状態を復元"""
		if 'L' in state:
			self.L.SetValue(state['L'])
		if 'B' in state:
			self.B.SetValue(state['B'])
		if 'H' in state:
			self.H.SetValue(state['H'])
		if 't_rect' in state:
			self.t_rect.SetValue(state['t_rect'])
		if 'main_vertical_beams' in state:
			self.main_vertical_beams.SetValue(state['main_vertical_beams'])
		if 'section_type' in state:
			self.section_type.SetSelection(state['section_type'])
		if 'H_tot' in state:
			self.H_tot.SetValue(state['H_tot'])
		if 'bf' in state:
			self.bf.SetValue(state['bf'])
		if 'tf' in state:
			self.tf.SetValue(state['tf'])
		if 'tw' in state:
			self.tw.SetValue(state['tw'])
		if 'material_choice' in state:
			self.material_choice.SetSelection(state['material_choice'])
		if 'tensile' in state:
			self.tensile.SetValue(state['tensile'])
		if 'yield_pt' in state:
			self.yield_pt.SetValue(state['yield_pt'])
		if 'factor' in state:
			self.factor.SetValue(state['factor'])
		# 面支持剛性係数 α
		if 'support_area_alpha' in state and hasattr(self, 'support_area_alpha'):
			self.support_area_alpha.SetValue(str(state['support_area_alpha']))
		# グリッドのデータを復元
		if 'load_rows' in state:
			# 既存の行をクリア
			if self.load_grid.GetNumberRows() > 0:
				self.load_grid.DeleteRows(0, self.load_grid.GetNumberRows())
			# 新しい行を追加
			for name, weight, position in state['load_rows']:
				self.load_grid.AppendRows(1)
				r = self.load_grid.GetNumberRows() - 1
				self.load_grid.SetCellValue(r, 0, name)
				self.load_grid.SetCellValue(r, 1, weight)
				self.load_grid.SetCellValue(r, 2, position)
		# 面荷重/面支持のデータを復元（新仕様）
		if 'dist_rows' in state:
			if self.dist_load_grid.GetNumberRows() > 0:
				self.dist_load_grid.DeleteRows(0, self.dist_load_grid.GetNumberRows())
			for row in state['dist_rows']:
				self.dist_load_grid.AppendRows(1)
				r = self.dist_load_grid.GetNumberRows() - 1
				for c, val in enumerate(row):
					if c < self.dist_load_grid.GetNumberCols():
						self.dist_load_grid.SetCellValue(r, c, val)
		# セクションデータを復元
		if 'section_rows' in state and hasattr(self, 'sections_grid'):
			if self.sections_grid.GetNumberRows() > 0:
				self.sections_grid.DeleteRows(0, self.sections_grid.GetNumberRows())
			for row_data in state['section_rows']:
				self.sections_grid.AppendRows(1)
				r = self.sections_grid.GetNumberRows() - 1
				if len(row_data) == 7:  # 新しい形式：横梁本数を含む
					x1, x2, nbeams_v, nbeams_h, b, h, t = row_data
					self.sections_grid.SetCellValue(r, 0, x1)
					self.sections_grid.SetCellValue(r, 1, x2)
					self.sections_grid.SetCellValue(r, 2, nbeams_v)
					self.sections_grid.SetCellValue(r, 3, nbeams_h)
					self.sections_grid.SetCellValue(r, 4, b)
					self.sections_grid.SetCellValue(r, 5, h)
					self.sections_grid.SetCellValue(r, 6, t)
				elif len(row_data) == 6:  # 旧形式：互換性のため
					x1, x2, nbeams, b, h, t = row_data
					self.sections_grid.SetCellValue(r, 0, x1)
					self.sections_grid.SetCellValue(r, 1, x2)
					self.sections_grid.SetCellValue(r, 2, nbeams)
					self.sections_grid.SetCellValue(r, 3, '1')  # デフォルト横梁本数
					self.sections_grid.SetCellValue(r, 4, b)
					self.sections_grid.SetCellValue(r, 5, h)
					self.sections_grid.SetCellValue(r, 6, t)
		# 表示を更新
		self._update_section_type()
		self._update_material()

class MainFrame(wx.Frame):
	def __init__(self):
		super().__init__(None,title='車両関連 統合計算ツール',size=wx.Size(1200,900))
		
		# アイコン設定
		icon_path = 'app_icon.ico'
		if os.path.exists(icon_path):
			try:
				self.SetIcon(wx.Icon(icon_path, wx.BITMAP_TYPE_ICO))
			except Exception as e:
				print(f"アイコン読み込みエラー: {e}")
		
		self.scroll = wx.ScrolledWindow(self, style=wx.VSCROLL|wx.HSCROLL)
		self.scroll.SetScrollRate(20, 20)
		self.nb=wx.Notebook(self.scroll, style=wx.NB_MULTILINE)
		self.panels = [
			('重量計算', WeightCalcPanel(self.nb)),
			('ハンガー荷重分配', HangerLoadDistributionPanel(self.nb)),
			('タイヤ負荷率・接地圧', TireLoadContactPanel(self.nb)),
			('連結仕様', TrailerSpecPanel(self.nb)),
			('安定角度', StabilityAnglePanel(self.nb)),
			('旋回半径', TurningRadiusPanel(self.nb)),
			('車軸強度', AxleStrengthPanel(self.nb)),
			('車枠強度（新）', VehicleFrameStrengthPanel(self.nb)),
			('制動装置強度', BrakeStrengthPanel(self.nb)),
			('牽引車諸元', TowingSpecPanel(self.nb)),
			('緩衝装置強度', LeafSpringCushionStrengthPanel(self.nb)),
			('板ばね分布', TwoAxleLeafSpringPanel(self.nb)),
			('安全チェーン', SafetyChainPanel(self.nb)),
			('保安基準適合検討表', Form2Panel(self.nb)),
		]
		self.original_titles = [title for title, _ in self.panels]
		# 重量計算パネルへの直接参照を保持しておく（他パネルから安全に参照するため）
		self.weight_panel = self.panels[0][1] if self.panels else None
		for title, panel in self.panels:
			self.nb.AddPage(panel, title)
		sizer = wx.BoxSizer(wx.VERTICAL)
		sizer.Add(self.nb, 1, wx.EXPAND)
		self.scroll.SetSizer(sizer)
		main_sizer = wx.BoxSizer(wx.VERTICAL)
		main_sizer.Add(self.scroll, 1, wx.EXPAND)
		self.SetSizer(main_sizer)
		self.current_project_path = None
		# 最近使ったファイルの履歴
		self.recent_files = self._load_recent_files()
		self.recent_menu_items = []
		# タブ変更時に未入力チェック
		self.nb.Bind(wx.EVT_NOTEBOOK_PAGE_CHANGED, self.on_tab_changed)
		# テキスト変更ハンドラを設定
		wx.CallAfter(self.setup_text_change_handlers)
		# 初回チェック
		wx.CallAfter(self.update_tab_marks)
		# メニューバー
		menubar = wx.MenuBar()
		file_menu = wx.Menu()
		file_menu.Append(wx.ID_NEW, '新規プロジェクト\tCtrl+N')
		file_menu.Append(wx.ID_OPEN, 'プロジェクトを開く\tCtrl+O')
		# 最近使ったファイルのサブメニュー
		self.recent_menu = wx.Menu()
		file_menu.AppendSubMenu(self.recent_menu, '最近使ったファイル')
		self._update_recent_menu()
		file_menu.AppendSeparator()
		file_menu.Append(wx.ID_SAVE, 'プロジェクト保存\tCtrl+S')
		file_menu.Append(wx.ID_SAVEAS, '名前を付けて保存\tCtrl+Shift+S')
		file_menu.AppendSeparator()
		self.export_all_id = wx.NewIdRef()
		file_menu.Append(self.export_all_id, '総合書類一括発行\tCtrl+E')
		self.export_unified_id = wx.NewIdRef()
		file_menu.Append(self.export_unified_id, '総合書類（単一PDF）発行...')
		file_menu.AppendSeparator()
		file_menu.Append(wx.ID_EXIT, '終了\tCtrl+Q')
		menubar.Append(file_menu, 'ファイル(&F)')
		self.SetMenuBar(menubar)
		self.Bind(wx.EVT_MENU, self.on_new_project, id=wx.ID_NEW)
		self.Bind(wx.EVT_MENU, self.on_open_project, id=wx.ID_OPEN)
		self.Bind(wx.EVT_MENU, self.on_save_project, id=wx.ID_SAVE)
		self.Bind(wx.EVT_MENU, self.on_save_as_project, id=wx.ID_SAVEAS)
		self.Bind(wx.EVT_MENU, self.on_export_all, id=self.export_all_id)
		self.Bind(wx.EVT_MENU, self.on_exit, id=wx.ID_EXIT)
		self.Bind(wx.EVT_MENU, self.on_export_unified, id=self.export_unified_id)
		self.Centre()

	def _load_recent_files(self):
		"""最近使ったファイルの履歴を読み込む"""
		recent_file_path = os.path.join(os.path.expanduser('~'), '.trailer_app_recent.json')
		try:
			if os.path.exists(recent_file_path):
				with open(recent_file_path, 'r', encoding='utf-8') as f:
					recent = json.load(f)
					# ファイルが存在するもののみ保持
					return [path for path in recent if os.path.exists(path)][:10]
		except Exception:
			pass
		return []
	
	def _save_recent_files(self):
		"""最近使ったファイルの履歴を保存"""
		recent_file_path = os.path.join(os.path.expanduser('~'), '.trailer_app_recent.json')
		try:
			with open(recent_file_path, 'w', encoding='utf-8') as f:
				json.dump(self.recent_files[:10], f, ensure_ascii=False, indent=2)
		except Exception:
			pass
	
	def _add_to_recent_files(self, path):
		"""履歴にファイルを追加"""
		# 既存の場合は削除してから先頭に追加
		if path in self.recent_files:
			self.recent_files.remove(path)
		self.recent_files.insert(0, path)
		self.recent_files = self.recent_files[:10]  # 最大10件
		self._save_recent_files()
		self._update_recent_menu()
	
	def _update_recent_menu(self):
		"""最近使ったファイルのメニューを更新"""
		# 既存のメニューアイテムをクリア
		for item in self.recent_menu_items:
			self.recent_menu.Delete(item)
		self.recent_menu_items.clear()
		
		if not self.recent_files:
			item = self.recent_menu.Append(wx.ID_ANY, '（履歴なし）')
			item.Enable(False)
			self.recent_menu_items.append(item)
		else:
			for i, path in enumerate(self.recent_files):
				filename = os.path.basename(path)
				label = f'{i+1}. {filename}'
				item_id = wx.NewIdRef()
				item = self.recent_menu.Append(item_id, label)
				self.recent_menu_items.append(item)
				self.Bind(wx.EVT_MENU, lambda evt, p=path: self._open_recent_file(p), id=item_id)
			
			if self.recent_files:
				self.recent_menu.AppendSeparator()
				clear_id = wx.NewIdRef()
				clear_item = self.recent_menu.Append(clear_id, '履歴をクリア')
				self.recent_menu_items.append(clear_item)
				self.Bind(wx.EVT_MENU, self._clear_recent_files, id=clear_id)
	
	def _open_recent_file(self, path):
		"""履歴から選択したファイルを開く"""
		if not os.path.exists(path):
			wx.MessageBox(f'ファイルが見つかりません:\n{path}', 'エラー', wx.ICON_ERROR)
			self.recent_files.remove(path)
			self._save_recent_files()
			self._update_recent_menu()
			return
		
		self._load_project_from_path(path)
	
	def _clear_recent_files(self, _):
		"""履歴をクリア"""
		res = wx.MessageBox('最近使ったファイルの履歴をクリアしますか？', '確認', wx.YES_NO|wx.ICON_QUESTION)
		if res == wx.YES:
			self.recent_files.clear()
			self._save_recent_files()
			self._update_recent_menu()

	def setup_text_change_handlers(self):
		"""全TextCtrlに変更イベントハンドラを設定"""
		def walk_and_bind(widget):
			for child in widget.GetChildren():
				if isinstance(child, wx.TextCtrl):
					child.Bind(wx.EVT_TEXT, self.on_text_changed)
				walk_and_bind(child)
		
		for _, panel in self.panels:
			walk_and_bind(panel)

	def on_text_changed(self, event):
		"""テキスト変更時にタブマークを更新（遅延実行）"""
		# 頻繁な更新を避けるため、少し遅延させる
		if hasattr(self, '_update_timer'):
			self._update_timer.Stop()
		self._update_timer = wx.CallLater(300, self.update_tab_marks)
		event.Skip()

	def on_tab_changed(self, event):
		"""タブ変更時に全タブの未入力マークを更新"""
		wx.CallAfter(self.update_tab_marks)
		event.Skip()

	def has_empty_fields(self, panel):
		"""パネルに未入力フィールドがあるかチェック"""
		def check_control(ctrl):
			"""コントロールが空かどうかチェック"""
			if isinstance(ctrl, wx.TextCtrl):
				value = ctrl.GetValue().strip()
				return len(value) == 0
			return False
		
		def walk_children(widget):
			"""再帰的に子ウィジェットをチェック"""
			empty_count = 0
			for child in widget.GetChildren():
				if check_control(child):
					empty_count += 1
				empty_count += walk_children(child)
			return empty_count
		
		return walk_children(panel) > 0

	def update_tab_marks(self):
		"""全タブの未入力マークを更新"""
		for i, (original_title, panel) in enumerate(zip(self.original_titles, [p for _, p in self.panels])):
			has_empty = self.has_empty_fields(panel)
			if has_empty:
				new_title = f"* {original_title}"
			else:
				new_title = original_title
			
			# タブのテキストを更新
			current_text = self.nb.GetPageText(i)
			if current_text != new_title:
				self.nb.SetPageText(i, new_title)

	def on_new_project(self, _):
		if wx.MessageBox('現在の入力内容をクリアして新規プロジェクトを作成しますか？','確認',wx.YES_NO|wx.ICON_QUESTION) != wx.YES:
			return
		for _, panel in self.panels:
			if hasattr(panel, 'set_state'):
				panel.set_state({})
		self.current_project_path = None
		self.SetTitle('車両関連 統合計算ツール - 新規プロジェクト')
		wx.CallAfter(self.update_tab_marks)
		wx.MessageBox('新規プロジェクトを作成しました。','完了',wx.ICON_INFORMATION)

	def on_open_project(self, _):
		with wx.FileDialog(self, '開くプロジェクトファイル', wildcard='Project files (*.kjt;*.json)|*.kjt;*.json', style=wx.FD_OPEN|wx.FD_FILE_MUST_EXIST) as dlg:
			if dlg.ShowModal() != wx.ID_OK:
				return
			path = dlg.GetPath()
		self._load_project_from_path(path)
	
	def _load_project_from_path(self, path):
		"""指定されたパスからプロジェクトを読み込む"""
		try:
			# ファイル形式を判定
			if path.lower().endswith('.kjt'):
				# gzip圧縮JSON形式
				with gzip.open(path, 'rt', encoding='utf-8') as f:
					data = json.load(f)
			else:
				# 従来のJSON形式
				with open(path, 'r', encoding='utf-8') as f:
					data = json.load(f)
			for title, panel in self.panels:
				if hasattr(panel, 'set_state'):
					panel.set_state(data.get(title, {}))
			self.current_project_path = path
			self.SetTitle(f'車両関連 統合計算ツール - {os.path.basename(path)}')
			self._add_to_recent_files(path)
			wx.CallAfter(self.update_tab_marks)
			wx.MessageBox(f'プロジェクトを読み込みました:\n{path}','完了',wx.ICON_INFORMATION)
		except Exception as e:
			wx.MessageBox(f'読み込みエラー: {e}','エラー',wx.ICON_ERROR)

	def on_save_project(self, _):
		if self.current_project_path:
			self._save_to_path(self.current_project_path)
		else:
			self.on_save_as_project(_)

	def on_save_as_project(self, _):
		with wx.FileDialog(self, 'プロジェクトを保存', wildcard='KJT files (*.kjt)|*.kjt|Project files (*.json)|*.json', style=wx.FD_SAVE|wx.FD_OVERWRITE_PROMPT, defaultFile='trailer_project.kjt') as dlg:
			if dlg.ShowModal() != wx.ID_OK:
				return
			path = dlg.GetPath()
			# .kjt拡張子がなければ追加
			if not path.lower().endswith('.kjt') and not path.lower().endswith('.json'):
				path += '.kjt'
			self._save_to_path(path)

	def _save_to_path(self, path):
		try:
			data = {}
			for title, panel in self.panels:
				if hasattr(panel, 'get_state'):
					data[title] = panel.get_state()
			# ファイル形式に応じて保存
			if path.lower().endswith('.kjt'):
				# gzip圧縮JSON形式で保存
				with gzip.open(path, 'wt', encoding='utf-8') as f:
					json.dump(data, f, ensure_ascii=False, indent=2)
			else:
				# 従来のJSON形式で保存
				with open(path, 'w', encoding='utf-8') as f:
					json.dump(data, f, ensure_ascii=False, indent=2)
			self.current_project_path = path
			self.SetTitle(f'車両関連 統合計算ツール - {os.path.basename(path)}')
			self._add_to_recent_files(path)
			wx.CallAfter(self.update_tab_marks)
			wx.MessageBox(f'プロジェクトを保存しました:\n{path}','完了',wx.ICON_INFORMATION)
		except Exception as e:
			wx.MessageBox(f'保存エラー: {e}','エラー',wx.ICON_ERROR)

	def on_export_all(self, _):
		if not _REPORTLAB_AVAILABLE:
			wx.MessageBox('ReportLabが未インストールです。','PDF出力不可',wx.ICON_ERROR)
			return
		with wx.DirDialog(self, '総合書類の出力先フォルダを選択', style=wx.DD_DEFAULT_STYLE) as dlg:
			if dlg.ShowModal() != wx.ID_OK:
				return
			output_dir = dlg.GetPath()
		try:
			os.makedirs(output_dir, exist_ok=True)
			generated = []
			for title, panel in self.panels:
				# 各パネルに export_to_path があれば試行（パネル側で未計算時は何もしない実装）
				if hasattr(panel, 'export_to_path'):
					filename = f"{title}.pdf"
					pdf_path = os.path.join(output_dir, filename)
					# 各パネルのPDF出力を直接実行（ダイアログ表示を回避）
					try:
						self._export_panel_pdf(panel, pdf_path)
						generated.append(filename)
					except Exception as pe:
						print(f'{title} PDF生成エラー: {pe}')
			wx.MessageBox(f'総合書類を出力しました:\n{output_dir}\n\n生成ファイル:\n' + '\n'.join(generated), '完了', wx.ICON_INFORMATION)
		except Exception as e:
			wx.MessageBox(f'一括出力エラー: {e}','エラー',wx.ICON_ERROR)

	def on_export_unified(self, _):
		"""全パネルを1本のPDFに統合して出力"""
		with wx.FileDialog(self, '総合書類（単一PDF）を保存', wildcard='PDF files (*.pdf)|*.pdf', style=wx.FD_SAVE|wx.FD_OVERWRITE_PROMPT, defaultFile='総合計算書.pdf') as dlg:
			if dlg.ShowModal() != wx.ID_OK:
				return
			dest_path = dlg.GetPath()
		# 一時フォルダに各PDFを出力
		tmp_dir = tempfile.mkdtemp(prefix='trailer_unified_')
		paths = []
		for idx, (title, panel) in enumerate(self.panels, start=1):
			if hasattr(panel, 'export_to_path'):
				fname = f"{idx:02d}_{re.sub(r'[\\/:*?\"<>|]', '_', title)}.pdf"
				p = os.path.join(tmp_dir, fname)
				try:
					panel.export_to_path(p)
					if os.path.exists(p) and os.path.getsize(p) > 0:
						paths.append(p)
				except Exception as _:
					pass
		# PyPDF2 があれば結合、なければサマリPDFを生成
		try:
			if _PYPDF2_AVAILABLE and paths:
				merger = _PdfMerger()
				for p in paths:
					merger.append(p)
				with open(dest_path, 'wb') as f:
					merger.write(f)
				merger.close()
			else:
				# フォールバック: 簡易サマリPDF
				self._export_unified_summary(dest_path)
			wx.MessageBox(f'総合書類（単一PDF）を保存しました:\n{dest_path}','完了',wx.ICON_INFORMATION)
		except Exception as e:
			wx.MessageBox(f'総合PDF作成エラー: {e}','エラー',wx.ICON_ERROR)
		finally:
			try:
				shutil.rmtree(tmp_dir)
			except Exception:
				pass

	def _export_unified_summary(self, path: str) -> None:
		"""テンプレートなしの簡易サマリPDFを生成"""
		if not _REPORTLAB_AVAILABLE:
			return
		c = _pdf_canvas.Canvas(path, pagesize=_A4)
		W,H = _A4
		font='Helvetica'
		for f in ['C:/Windows/Fonts/msgothic.ttc', 'C:/Windows/Fonts/meiryo.ttc', 'C:/Windows/Fonts/yugothic.ttf', 'ipaexg.ttf','ipaexm.ttf','fonts/ipaexg.ttf','fonts/ipaexm.ttf']:
			if os.path.exists(f):
				try:
					_pdfmetrics.registerFont(_TTFont('JPUnified',f)); font='JPUnified'; break
				except Exception: pass
		left=40; y=H-40
		c.setFont(font,16); c.drawString(left,y,'総合計算書'); y-=28; c.setFont(font,9)
		for title, panel in self.panels:
			# 見出し
			c.setFont(font,12); c.drawString(left,y,f'■ {title}'); y-=16; c.setFont(font,9)
			# 可能なら get_state の内容を簡易表で列挙
			try:
				state = panel.get_state() if hasattr(panel,'get_state') else {}
				rows = []
				# 代表的な結果キー候補
				for key in ('last','last_data','last_values'):
					val = state.get(key) if isinstance(state, dict) else None
					if isinstance(val, dict):
						for i,(k,v) in enumerate(val.items()):
							rows.append((k, str(v)))
							if i>=12: break
						break
				if not rows and isinstance(state, dict):
					for i,(k,v) in enumerate(state.items()):
						if k in ('inputs','material','chain_path'): continue
						rows.append((k, str(v)))
						if i>=10: break
				# 表描画
				row_h=14; col_w=[180,300]
				if rows:
					c.rect(left, y-row_h*len(rows), sum(col_w), row_h*len(rows))
					cx=left
					c.line(cx, y, cx, y-row_h*len(rows)); cx+=col_w[0]; c.line(cx, y, cx, y-row_h*len(rows)); c.line(cx+col_w[1], y, cx+col_w[1], y-row_h*len(rows))
					for i in range(1,len(rows)):
						c.line(left, y-row_h*i, left+sum(col_w), y-row_h*i)
					for i,(k,v) in enumerate(rows):
						c.drawString(left+4, y-row_h*i-10, str(k))
						c.drawString(left+col_w[0]+4, y-row_h*i-10, str(v))
					y -= row_h*len(rows) + 10
				else:
					c.drawString(left, y, '(データなし)'); y-=14
			except Exception:
				c.drawString(left, y, '(取得エラー)'); y-=14
			# ページ余白
			if y < 100:
				c.showPage(); y=H-40; c.setFont(font,9)
		c.showPage(); c.save()

	def _export_panel_pdf(self, panel, path):
		"""各パネルのPDF出力ロジックを直接実行（ダイアログなし）"""
		if hasattr(panel, 'export_to_path'):
			panel.export_to_path(path)

	def on_exit(self, _):
		self.Close()

def main():
	# SetTopWindow でトップウィンドウを明示することで、環境依存でイベントループが即終了する問題を防ぐ。
	app = wx.App(False)
	frame = MainFrame()
	app.SetTopWindow(frame)
	frame.Show()
	app.MainLoop()

if __name__=='__main__':
	main()
