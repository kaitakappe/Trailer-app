import wx
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
	compute_hitch_strength, format_hitch_strength_result
)
from lib.form_issuer import (
	Form1Data, Form2Data, collect_calculation_data, auto_fill_form1_data, auto_fill_form2_data, generate_form1_pdf, generate_form2_pdf,
	OverviewData, auto_fill_overview_data, generate_overview_pdf
)

# 共通結果表示ウィンドウ (全パネルから利用) / 車枠強度グラフウィンドウ
RESULT_WINDOW = None
FRAME_GRAPH_WINDOW = None

class FrameGraphWindow(wx.Frame):
	def __init__(self):
		super().__init__(None, title='車枠強度グラフ', size=wx.Size(960, 420))
		self.bmp = wx.StaticBitmap(self, bitmap=wx.BitmapBundle.FromBitmap(wx.Bitmap(960, 360)))
		sizer = wx.BoxSizer(wx.VERTICAL)
		sizer.Add(self.bmp, 1, wx.EXPAND|wx.ALL, 6)
		self.SetSizer(sizer)
		self.Bind(wx.EVT_CLOSE, self.on_close)
	def on_close(self, event):
		global FRAME_GRAPH_WINDOW
		FRAME_GRAPH_WINDOW = None
		self.Destroy()
	def set_data(self, data: dict):
		try:
			path = create_frame_diagram_png(data)
			if path:
				b = wx.Bitmap(path, wx.BITMAP_TYPE_PNG)
				self.bmp.SetBitmap(wx.BitmapBundle.FromBitmap(b))
				self.Layout()
		except Exception:
			pass

class ResultWindow(wx.Frame):
	def __init__(self):
		super().__init__(None, title='計算結果', size=wx.Size(560, 620))
		self.txt = wx.TextCtrl(self, style=wx.TE_MULTILINE|wx.TE_READONLY|wx.VSCROLL)
		sizer = wx.BoxSizer(wx.VERTICAL)
		sizer.Add(self.txt, 1, wx.EXPAND|wx.ALL, 4)
		self.SetSizer(sizer)
		self.Bind(wx.EVT_CLOSE, self.on_close)
	def on_close(self, event):
		global RESULT_WINDOW
		RESULT_WINDOW = None
		self.Destroy()
	def set_text(self, text: str):
		self.txt.SetValue(text)
	def set_content(self, title: str, text: str):
		try:
			self.SetTitle(title)
		except Exception:
			pass
		self.txt.SetValue(text)

def show_frame_graph(data: dict):
	"""車枠強度グラフを別ウィンドウに表示/更新"""
	global FRAME_GRAPH_WINDOW
	if FRAME_GRAPH_WINDOW is None or not FRAME_GRAPH_WINDOW:
		FRAME_GRAPH_WINDOW = FrameGraphWindow()
	try:
		if not FRAME_GRAPH_WINDOW.IsShown():
			FRAME_GRAPH_WINDOW.Show()
		FRAME_GRAPH_WINDOW.set_data(data)
		FRAME_GRAPH_WINDOW.Raise()
	except RuntimeError:
		# ウィンドウが削除済みの場合、再作成
		FRAME_GRAPH_WINDOW = FrameGraphWindow()
		FRAME_GRAPH_WINDOW.Show()
		FRAME_GRAPH_WINDOW.set_data(data)
		FRAME_GRAPH_WINDOW.Raise()

def create_cross_section_diagram_png(B: float, H: float, b: float, h: float, tw: float=0, tf: float=0, cross_type: str='rect', width=300, height=300) -> str:
	"""断面図を生成してPNGパスを返す (mm単位)"""
	try:
		bmp = wx.Bitmap(width, height)
		dc = wx.MemoryDC(bmp)
		dc.SetBackground(wx.Brush(wx.Colour(255,255,255)))
		dc.Clear()
		# 中心位置
		cx, cy = width // 2, height // 2
		# スケール (最大寸法を基準に)
		max_dim = max(B, H)
		scale = min(200, (min(width, height) - 60) / max_dim) if max_dim > 0 else 1
		if cross_type == 'hbeam':
			# H形鋼
			w_outer = B * scale
			h_outer = H * scale
			w_web = tw * scale
			h_flange = tf * scale
			# 外形
			dc.SetBrush(wx.Brush(wx.Colour(180,180,180)))
			dc.SetPen(wx.Pen(wx.Colour(0,0,0),2))
			# 上フランジ
			dc.DrawRectangle(int(cx - w_outer/2), int(cy - h_outer/2), int(w_outer), int(h_flange))
			# ウェブ
			dc.DrawRectangle(int(cx - w_web/2), int(cy - h_outer/2 + h_flange), int(w_web), int(h_outer - 2*h_flange))
			# 下フランジ
			dc.DrawRectangle(int(cx - w_outer/2), int(cy + h_outer/2 - h_flange), int(w_outer), int(h_flange))
			# 寸法線
			dc.SetPen(wx.Pen(wx.Colour(100,100,100),1))
			dc.SetTextForeground(wx.Colour(0,0,0))
			dc.SetFont(wx.Font(9, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL))
			# B寸法
			y_dim = int(cy - h_outer/2 - 15)
			dc.DrawLine(int(cx - w_outer/2), y_dim, int(cx + w_outer/2), y_dim)
			dc.DrawText(f'B={B:.1f}', int(cx - 30), y_dim - 15)
			# H寸法
			x_dim = int(cx + w_outer/2 + 15)
			dc.DrawLine(x_dim, int(cy - h_outer/2), x_dim, int(cy + h_outer/2))
			dc.DrawText(f'H={H:.1f}', x_dim + 5, int(cy - 10))
			# tw寸法 (ウェブの外側に表示)
			dc.DrawText(f'tw={tw:.1f}', int(cx + w_web/2 + 8), int(cy))
			# tf寸法 (上フランジの外側に表示)
			dc.DrawText(f'tf={tf:.1f}', int(cx - w_outer/2 - 45), int(cy - h_outer/2 + h_flange/2))
		else:
			# 中抜き矩形
			w_outer = B * scale
			h_outer = H * scale
			w_inner = b * scale
			h_inner = h * scale
			# 外形（グレー塗りつぶし）
			dc.SetBrush(wx.Brush(wx.Colour(180,180,180)))
			dc.SetPen(wx.Pen(wx.Colour(0,0,0),2))
			dc.DrawRectangle(int(cx - w_outer/2), int(cy - h_outer/2), int(w_outer), int(h_outer))
			# 内空部（白抜き）
			dc.SetBrush(wx.Brush(wx.Colour(255,255,255)))
			dc.SetPen(wx.Pen(wx.Colour(0,0,0),1))
			dc.DrawRectangle(int(cx - w_inner/2), int(cy - h_inner/2), int(w_inner), int(h_inner))
			# 寸法線
			dc.SetPen(wx.Pen(wx.Colour(100,100,100),1))
			dc.SetTextForeground(wx.Colour(0,0,0))
			dc.SetFont(wx.Font(9, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL))
			# B寸法（上）
			y_dim = int(cy - h_outer/2 - 15)
			dc.DrawLine(int(cx - w_outer/2), y_dim, int(cx + w_outer/2), y_dim)
			dc.DrawText(f'B={B:.1f}', int(cx - 30), y_dim - 15)
			# H寸法（右）
			x_dim = int(cx + w_outer/2 + 15)
			dc.DrawLine(x_dim, int(cy - h_outer/2), x_dim, int(cy + h_outer/2))
			dc.DrawText(f'H={H:.1f}', x_dim + 5, int(cy - 10))
			# b寸法（内側上）
			y_dim_inner = int(cy - h_inner/2 + 15)
			dc.DrawLine(int(cx - w_inner/2), y_dim_inner, int(cx + w_inner/2), y_dim_inner)
			dc.DrawText(f'b={b:.1f}', int(cx - 25), y_dim_inner - 15)
			# h寸法（内側右）
			x_dim_inner = int(cx + w_inner/2 - 15)
			dc.DrawLine(x_dim_inner, int(cy - h_inner/2), x_dim_inner, int(cy + h_inner/2))
			dc.DrawText(f'h={h:.1f}', x_dim_inner - 35, int(cy))
		dc.SelectObject(wx.NullBitmap)
		fd, path = tempfile.mkstemp(suffix='.png', prefix='cross_section_')
		os.close(fd)
		bmp.SaveFile(path, wx.BITMAP_TYPE_PNG)
		return path
	except Exception:
		return ''

def create_container_seating_diagram_png(span: float, front: float, rear: float, x1: float, x2: float, coupler_offset: float=0, width=700, height=280) -> str:
	"""コンテナ4点座配置図を生成しPNGパスを返す (mm単位入力)"""
	try:
		bmp = wx.Bitmap(width, height)
		dc = wx.MemoryDC(bmp)
		dc.SetBackground(wx.Brush(wx.Colour(255,255,255)))
		dc.Clear()
		margin_x = 60
		beam_y = 140
		# スケール計算 (カプラ位置を含めた全長)
		total_length = coupler_offset + span
		scale = (width - 2*margin_x) / float(total_length)
		def to_x(pos_mm): return int(margin_x + pos_mm * scale)
		# カプラ位置 (赤マーカー)
		dc.SetBrush(wx.Brush(wx.Colour(255,0,0)))
		dc.SetPen(wx.Pen(wx.Colour(200,0,0),2))
		dc.DrawCircle(to_x(0), beam_y, 8)
		dc.SetTextForeground(wx.Colour(200,0,0))
		dc.SetFont(wx.Font(9, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD))
		dc.DrawText('カプラ', to_x(0)-20, beam_y-25)
		# 縦桁 (梁)
		dc.SetPen(wx.Pen(wx.Colour(0,0,0),3))
		dc.DrawLine(to_x(coupler_offset), beam_y, to_x(coupler_offset+span), beam_y)
		# 4点座 (オレンジ丸: 前側2点, 後側2点)
		pad_front1 = coupler_offset + front  # C + a
		pad_front2 = coupler_offset + front  # C + a
		pad_rear1 = coupler_offset + (span - rear)  # C + L - b
		pad_rear2 = coupler_offset + (span - rear)  # C + L - b
		dc.SetBrush(wx.Brush(wx.Colour(255,140,0)))
		dc.SetPen(wx.Pen(wx.Colour(255,100,0),2))
		for pos in [pad_front1, pad_rear1]:
			dc.DrawCircle(to_x(pos), beam_y, 12)
		# ラベル
		dc.SetTextForeground(wx.Colour(255,100,0))
		dc.SetFont(wx.Font(10, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD))
		dc.DrawText('前座', to_x(pad_front1)-18, beam_y-32)
		dc.DrawText('後座', to_x(pad_rear1)-18, beam_y-32)
		# 支点 (青三角: X1, X2)
		dc.SetBrush(wx.Brush(wx.Colour(0,100,200)))
		dc.SetPen(wx.Pen(wx.Colour(0,80,180),2))
		for xpos in [coupler_offset+x1, coupler_offset+x2]:
			sx = to_x(xpos)
			pts = [wx.Point(sx-10, beam_y+10), wx.Point(sx, beam_y+26), wx.Point(sx+10, beam_y+10)]
			dc.DrawPolygon(pts)
		dc.SetTextForeground(wx.Colour(0,80,180))
		dc.DrawText('X1', to_x(coupler_offset+x1)-8, beam_y+32)
		dc.DrawText('X2', to_x(coupler_offset+x2)-8, beam_y+32)
		# 寸法線 (グレー点線)
		dc.SetPen(wx.Pen(wx.Colour(120,120,120),1,wx.PENSTYLE_SHORT_DASH))
		dim_y = beam_y + 60
		for pos in [0, coupler_offset, coupler_offset+front, coupler_offset+x1, coupler_offset+x2, coupler_offset+span-rear, coupler_offset+span]:
			dc.DrawLine(to_x(pos), beam_y+4, to_x(pos), dim_y+8)
		# 寸法値
		dc.SetTextForeground(wx.Colour(0,0,0))
		dc.SetFont(wx.Font(8, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL))
		dc.DrawText(f'C={coupler_offset:.0f}', to_x(coupler_offset/2)-20, dim_y-8)
		dc.DrawText(f'a={front:.0f}', to_x(coupler_offset+front/2)-20, dim_y+16)
		dc.DrawText(f'X1={x1:.0f}', to_x(coupler_offset+x1)-20, dim_y+24)
		dc.DrawText(f'X2={x2:.0f}', to_x(coupler_offset+x2)-20, dim_y+24)
		dc.DrawText(f'b={rear:.0f}', to_x(coupler_offset+(span+span-rear)/2)-20, dim_y+16)
		dc.DrawText(f'L={span:.0f}', to_x(coupler_offset+span/2)-20, beam_y-60)
		# 凡例
		dc.SetFont(wx.Font(9, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL))
		dc.SetTextForeground(wx.Colour(0,0,0))
		dc.DrawText('● 赤:カプラ(連結部)  ● 橙:コンテナ座(4点)  ▲ 青:サスペンションハンガー(支点)', 20, 20)
		dc.SelectObject(wx.NullBitmap)
		fd, path = tempfile.mkstemp(suffix='.png', prefix='container_seating_')
		os.close(fd)
		bmp.SaveFile(path, wx.BITMAP_TYPE_PNG)
		return path
	except Exception:
		return ''

def create_frame_diagram_png(data: dict, width=900, height=360) -> str:
	"""車枠強度図を一時PNGファイルとして生成しパスを返す"""
	if not data:
		return ''
	bmp = wx.Bitmap(width, height)
	dc = wx.MemoryDC(bmp)
	dc.SetBackground(wx.Brush(wx.Colour(255,255,255)))
	dc.Clear()
	margin = 50
	dists = data['dists']
	shear_vals = data['shear_list']
	moment_vals = data['moment_list']
	positions = [0]
	for d in dists:
		positions.append(positions[-1] + d)
	L = positions[-1]
	if L <= 0:
		dc.SelectObject(wx.NullBitmap)
		return ''
	x_scale = (width - 2*margin) / float(L)
	max_shear = max(abs(v) for v in shear_vals) if shear_vals else 1
	max_moment = max(abs(v) for v in moment_vals) if moment_vals else 1
	shear_top = margin
	shear_bottom = int(margin + (height - 2*margin) * 0.60)
	moment_top = shear_bottom + 18
	moment_bottom = height - margin
	dc.SetPen(wx.Pen(wx.Colour(0,0,0),1))
	dc.DrawLine(margin, shear_bottom, width-margin, shear_bottom)
	dc.DrawLine(margin, moment_bottom, width-margin, moment_bottom)
	dc.SetFont(wx.Font(10, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD))
	dc.DrawText('せん断力 (kg)', margin, shear_top-22)
	dc.DrawText('曲げモーメント (kg·cm)', margin, moment_top-18)
	grid_pen = wx.Pen(wx.Colour(225,225,225),1,style=wx.PENSTYLE_SHORT_DASH)
	dc.SetPen(grid_pen)
	for g in range(1,5):
		gy = int(shear_top + (shear_bottom - shear_top) * g / 5.0)
		dc.DrawLine(margin, gy, width-margin, gy)
	dc.SetPen(wx.Pen(wx.Colour(220,0,0),2))
	prev_x = margin
	prev_y = int(shear_bottom - (shear_vals[0]/max_shear) * (shear_bottom - shear_top))
	dc.DrawCircle(prev_x, prev_y, 2)
	for i, val in enumerate(shear_vals):
		x = int(margin + positions[i] * x_scale)
		y = int(shear_bottom - (val/max_shear) * (shear_bottom - shear_top))
		if i > 0:
			dc.DrawLine(prev_x, prev_y, x, prev_y)
			dc.DrawLine(x, prev_y, x, y)
		dc.DrawCircle(x, y, 2)
		prev_x, prev_y = x, y
	dc.SetFont(wx.Font(8, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL))
	for p in positions:
		x = int(margin + p * x_scale)
		dc.DrawLine(x, shear_bottom, x, shear_bottom+4)
		dc.DrawText(str(int(p)), x-10, shear_bottom+6)
	dc.SetPen(wx.Pen(wx.Colour(0,80,200),2))
	for i, mv in enumerate(moment_vals):
		x = int(margin + positions[i+1] * x_scale)
		y = int(moment_bottom - (mv/max_moment) * (moment_bottom - moment_top))
		dc.DrawLine(x, moment_bottom, x, y)
		dc.DrawCircle(x, y, 2)
	for p in positions:
		x = int(margin + p * x_scale)
		dc.DrawLine(x, moment_bottom, x, moment_bottom+4)
		dc.DrawText(str(int(p)), x-10, moment_bottom+6)
	dc.SetTextForeground(wx.Colour(0,0,0))
	dc.DrawText(f"Mmax={data['Mmax']:.1f}", width-margin-140, moment_top)
	dc.DrawText(f"Smax={max_shear:.1f}", width-margin-140, shear_top)
	dc.SetPen(wx.Pen(wx.Colour(185,185,185),1,style=wx.PENSTYLE_SHORT_DASH))
	dc.DrawRectangle(margin, shear_top, width-2*margin, shear_bottom - shear_top)
	dc.DrawRectangle(margin, moment_top, width-2*margin, moment_bottom - moment_top)
	dc.DrawText('赤:せん断力ステップ / 青:区間終端曲げモーメント', margin, height-24)
	dc.SelectObject(wx.NullBitmap)
	fd, path = tempfile.mkstemp(suffix='.png', prefix='frame_diagram_')
	os.close(fd)
	bmp.SaveFile(path, wx.BITMAP_TYPE_PNG)
	return path

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


class WeightCalcPanel(wx.Panel):
	vw: wx.TextCtrl
	ml: wx.TextCtrl
	fa: wx.TextCtrl
	ra: wx.TextCtrl
	tc: wx.TextCtrl
	tl: wx.TextCtrl
	cw: wx.TextCtrl
	ts_front: wx.TextCtrl
	ts_rear: wx.TextCtrl
	last_data: dict | None
	
	def __init__(self, parent):
		super().__init__(parent)
		v = wx.BoxSizer(wx.VERTICAL)
		self.vw = self._add(v, '車両重量 [kg]:', '', '2000')
		self.ml = self._add(v, '最大積載量 [kg]:', '', '1000')
		self.fa = self._add(v, '前軸重量 [kg]:', '', '1200')
		self.ra = self._add(v, '後軸重量 [kg]:', '', '1000')
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

	def _add(self, sizer, label, default='', hint='') -> wx.TextCtrl:
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
			data = compute_weight_metrics(
				float(self.vw.GetValue()), float(self.ml.GetValue()), 
				float(self.fa.GetValue()), float(self.ra.GetValue()),
				int(self.tc.GetValue()), float(self.tl.GetValue()), float(self.cw.GetValue()),
				self.ts_front.GetValue(), self.ts_rear.GetValue()
			)
		except ValueError:
			wx.MessageBox('数値入力を確認してください。', '入力エラー', wx.ICON_ERROR); return
		self.last_data = data
		text = '\n'.join([
			'◆ 重量計算結果 ◆',
			f"総重量: {data['total_weight']:.1f} kg",
			f"前軸タイヤ強度比: {data['front_strength_ratio']:.2f}",
			f"後軸タイヤ強度比: {data['rear_strength_ratio']:.2f}",
			f"前軸接地圧: {data['front_contact_pressure']:.1f} kg/cm (幅 {data['front_contact_width_cm_used']:.1f} cm)",
			f"後軸接地圧: {data['rear_contact_pressure']:.1f} kg/cm (幅 {data['rear_contact_width_cm_used']:.1f} cm)",
		])
		show_result('重量計算結果', text)

	def on_export_pdf(self, _):
		if self.last_data is None:
			wx.MessageBox('先に計算を実行してください。', 'PDF出力', wx.ICON_INFORMATION); return
		if not _REPORTLAB_AVAILABLE:
			wx.MessageBox('ReportLabが未インストールです。インストール後再試行してください。', 'PDF出力不可', wx.ICON_ERROR); return
		with wx.FileDialog(self, message='PDF保存', wildcard='PDF files (*.pdf)|*.pdf', style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT, defaultFile='重量計算結果.pdf') as dlg:
			if dlg.ShowModal() != wx.ID_OK:
				return
			path = dlg.GetPath()
		try:
			c = _pdf_canvas.Canvas(path, pagesize=_A4)
			w, h = _A4
			# 日本語フォント探索
			font_name = 'Helvetica'
			for f in ['C:/Windows/Fonts/msgothic.ttc', 'C:/Windows/Fonts/meiryo.ttc', 'C:/Windows/Fonts/yugothic.ttf', 'ipaexg.ttf', 'ipaexm.ttf', 'fonts/ipaexg.ttf', 'fonts/ipaexm.ttf']:
				if os.path.exists(f):
					try:
						_pdfmetrics.registerFont(_TTFont('JPFont', f))
						font_name = 'JPFont'
						break
					except Exception:
						pass

			def draw_table(x, y, col_widths, row_height, data_rows, header_font=font_name, body_font=font_name, header_size=11, body_size=10, title=None):
				"""罫線付きテーブル描画。data_rows: [ [cell,...], ... ]"""
				# タイトル
				if title:
					c.drawString(x, y + 6, title)
					y -= 14
				cols = len(col_widths)
				rows = len(data_rows)
				# 外枠
				width_total = sum(col_widths)
				c.setLineWidth(0.7)
				c.rect(x, y - rows * row_height, width_total, rows * row_height)
				# 縦線
				cx = x
				for wcol in col_widths[:-1]:
					cx += wcol
					c.line(cx, y, cx, y - rows * row_height)
				# 横線
				ry = y
				for _ in range(rows - 1):
					ry -= row_height
					c.line(x, ry, x + width_total, ry)
				# テキスト
				for r, row in enumerate(data_rows):
					cy = y - (r + 1) * row_height + 4
					c.setFont(body_font if r > 0 else header_font, body_size if r > 0 else header_size)
					cx = x + 3
					for ci, val in enumerate(row):
						c.drawString(cx, cy, str(val))
						cx += col_widths[ci]
				return y - rows * row_height - 30  # 次のブロック用Y

			# データ計算
			total_w = self.last_data['total_weight']
			front_ratio = self.last_data['front_strength_ratio']
			rear_ratio = self.last_data['rear_strength_ratio']
			front_pressure = self.last_data['front_contact_pressure']
			rear_pressure = self.last_data['rear_contact_pressure']

			# 1. 重量計算書
			c.setFont(font_name, 14)
			c.drawString(40, h - 50, '重量計算書')
			start_y = h - 70
			col_w1 = [120, 90, 90, 90]
			rows_w = [
				['', '合計(kg)', '前軸(kg)', '後軸(kg)'],
				['車両重量', f'{self.vw.GetValue()}', f'{self.fa.GetValue()}', f'{self.ra.GetValue()}'],
				['最大積載量', f'{self.ml.GetValue()}', '', ''],
				['車両総重量', f'{total_w:.1f}', '', '']
			]
			after_y = draw_table(40, start_y, col_w1, 18, rows_w)

			# 2. タイヤ強度計算書
			rows_tire_strength = [
				['', 'タイヤサイズ', '本数', '推奨荷重 (kg)', '荷重割合 (%)'],
				['前軸', self.ts_front.GetValue(), self.tc.GetValue(), f'{self.tl.GetValue()}', f'{front_ratio*100:.1f}'],
				['後軸', self.ts_rear.GetValue(), self.tc.GetValue(), f'{self.tl.GetValue()}', f'{rear_ratio*100:.1f}'],
			]
			col_w2 = [70, 110, 60, 120, 110]
			after_y2 = draw_table(40, after_y, col_w2, 18, rows_tire_strength, title='タイヤ強度計算書')

			# 3. タイヤ接地圧計算書
			rows_pressure = [
				['', 'タイヤサイズ', '本数', '接地幅 (cm)', '接地圧 (kg/cm)'],
				['前軸', self.ts_front.GetValue(), self.tc.GetValue(), f'{self.cw.GetValue()}', f'{front_pressure:.1f}'],
				['後軸', self.ts_rear.GetValue(), self.tc.GetValue(), f'{self.cw.GetValue()}', f'{rear_pressure:.1f}'],
			]
			col_w3 = [70, 110, 60, 120, 120]
			after_y3 = draw_table(40, after_y2, col_w3, 18, rows_pressure, title='タイヤ接地圧計算書')
			c.setFont(font_name, 9)
			c.drawString(40 + sum(col_w3) + 5, after_y2 + 5, '≦200kg/cm')

			c.showPage(); c.save()
			_open_saved_pdf(path)
			wx.MessageBox('PDFを保存しました。', '完了', wx.ICON_INFORMATION)
		except Exception as e:
			wx.MessageBox(f'PDF出力中にエラー: {e}', 'エラー', wx.ICON_ERROR)

	def export_to_path(self, path):
		"""ダイアログ無しで重量計算書PDFを出力"""
		if self.last_data is None or not _REPORTLAB_AVAILABLE:
			return
		try:
			c = _pdf_canvas.Canvas(path, pagesize=_A4)
			w, h = _A4
			font_name = 'Helvetica'
			for f in ['C:/Windows/Fonts/msgothic.ttc', 'C:/Windows/Fonts/meiryo.ttc', 'C:/Windows/Fonts/yugothic.ttf', 'ipaexg.ttf', 'ipaexm.ttf', 'fonts/ipaexg.ttf', 'fonts/ipaexm.ttf']:
				if os.path.exists(f):
					try:
						_pdfmetrics.registerFont(_TTFont('JPFont', f)); font_name = 'JPFont'; break
					except Exception:
						pass
			def draw_table(x, y, col_widths, row_height, data_rows, header_font=font_name, body_font=font_name, header_size=11, body_size=10, title=None):
				if title:
					c.drawString(x, y + 6, title)
					y -= 14
				cols = len(col_widths)
				rows = len(data_rows)
				width_total = sum(col_widths)
				c.setLineWidth(0.7)
				c.rect(x, y - rows * row_height, width_total, rows * row_height)
				cx = x
				for wcol in col_widths[:-1]:
					cx += wcol
					c.line(cx, y, cx, y - rows * row_height)
				ry = y
				for _ in range(rows - 1):
					ry -= row_height
					c.line(x, ry, x + width_total, ry)
				for r, row in enumerate(data_rows):
					cy = y - (r + 1) * row_height + 4
					c.setFont(body_font if r > 0 else header_font, body_size if r > 0 else header_size)
					cx = x + 3
					for ci, val in enumerate(row):
						c.drawString(cx, cy, str(val))
						cx += col_widths[ci]
				return y - rows * row_height - 30
			v = self.last_data
			# 1. 重量計算書
			c.setFont(font_name, 14)
			c.drawString(40, h - 50, '重量計算書')
			start_y = h - 70
			col_w1 = [120, 90, 90, 90]
			rows_w = [
				['', '合計(kg)', '前軸(kg)', '後軸(kg)'],
				['車両重量', f'{self.vw.GetValue()}', f'{self.fa.GetValue()}', f'{self.ra.GetValue()}'],
				['最大積載量', f'{self.ml.GetValue()}', '', ''],
				['車両総重量', f"{v['total_weight']:.1f}", '', '']
			]
			after_y = draw_table(40, start_y, col_w1, 18, rows_w)
			# 2. タイヤ強度
			rows_tire_strength = [
				['', 'タイヤサイズ', '本数', '推奨荷重 (kg)', '荷重割合 (%)'],
				['前軸', self.ts_front.GetValue(), self.tc.GetValue(), f'{self.tl.GetValue()}', f"{v['front_strength_ratio']*100:.1f}"],
				['後軸', self.ts_rear.GetValue(), self.tc.GetValue(), f'{self.tl.GetValue()}', f"{v['rear_strength_ratio']*100:.1f}"]
			]
			col_w2 = [70, 110, 60, 120, 110]
			after_y2 = draw_table(40, after_y, col_w2, 18, rows_tire_strength, title='タイヤ強度計算書')
			# 3. タイヤ接地圧
			rows_pressure = [
				['', 'タイヤサイズ', '本数', '接地幅 (cm)', '接地圧 (kg/cm)'],
				['前軸', self.ts_front.GetValue(), self.tc.GetValue(), f'{self.cw.GetValue()}', f"{v['front_contact_pressure']:.1f}"],
				['後軸', self.ts_rear.GetValue(), self.tc.GetValue(), f'{self.cw.GetValue()}', f"{v['rear_contact_pressure']:.1f}"]
			]
			col_w3 = [70, 110, 60, 120, 120]
			after_y3 = draw_table(40, after_y2, col_w3, 18, rows_pressure, title='タイヤ接地圧計算書')
			c.setFont(font_name, 9)
			c.drawString(40 + sum(col_w3) + 5, after_y2 + 5, '≦200kg/cm')
			# 根拠・考え方
			y2 = after_y3 - 8
			c.setFont(font_name, 11); c.drawString(40, y2, '根拠・考え方'); y2 -= 14; c.setFont(font_name, 9)
			c.drawString(45, y2, '・必要制動力 F は、質量×重力加速度×所要減速度係数に比例します。'); y2 -= 12
			c.drawString(45, y2, '・係数 k は車種想定に応じた目安（乗用車0.65/トラック・バス0.5）を用いています。'); y2 -= 12
			c.drawString(45, y2, '・転倒安定角は幾何関係より tanθ=(T/2)/H。接地圧目安≦200kg/cmは安全側の設計目安です。')
			c.showPage(); c.save()
		except Exception:
			pass

	def get_state(self) -> dict:
		"""パネルの状態を保存"""
		return {
			'vw': self.vw.GetValue(),
			'ml': self.ml.GetValue(),
			'fa': self.fa.GetValue(),
			'ra': self.ra.GetValue(),
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
		if 'fa' in state: self.fa.SetValue(str(state['fa']))
		if 'ra' in state: self.ra.SetValue(str(state['ra']))
		if 'tc' in state: self.tc.SetValue(str(state['tc']))
		if 'tl' in state: self.tl.SetValue(str(state['tl']))
		if 'cw' in state: self.cw.SetValue(str(state['cw']))
		if 'ts_front' in state: self.ts_front.SetValue(str(state['ts_front']))
		if 'ts_rear' in state: self.ts_rear.SetValue(str(state['ts_rear']))
		if 'last_data' in state: self.last_data = state['last_data']



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
			('T2f', 'キングピン安 T2f₂f (m)'),
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
				('キングピン安定幅 T₂f = T₁r', f"({T2f:.3f})", 'm'),
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
				(f'キングピン安定幅 T₂f = T₁r', f"{T2f:.3f}", 'm'),
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
				(f'キングピン安定幅 T₂f = T₁r', f"{T2f:.3f}", 'm'),
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



class CouplerStrengthPanel(wx.Panel):
	"""連結部フレーム強度計算パネル"""
	def __init__(self, parent):
		super().__init__(parent)
		self.last = None
		v = wx.BoxSizer(wx.VERTICAL)
		
		# タイトル
		t = wx.StaticText(self, label='連結部フレーム強度計算')
		f = t.GetFont(); f.PointSize += 2; f = f.Bold(); t.SetFont(f)
		v.Add(t, 0, wx.ALL, 6)
		
		# 入力フィールド
		grid = wx.FlexGridSizer(0, 4, 6, 8)
		
		# 荷重条件
		self.W = self._add(grid, '最大積載量 [kg]', '', '2000')
		self.Wp = self._add(grid, '装備品質量 [kg]', '', '800')
		
		# 寸法
		self.L = self._add(grid, '連結中心から荷台中心 [mm]', '', '2500')
		self.Lp = self._add(grid, '連結中心から装備品 [mm]', '', '1500')
		self.Lf = self._add(grid, 'フレーム長さ [mm]', '', '1000')
		
		# 断面諸元（矩形）
		self.B = self._add(grid, 'フレーム幅 B [mm]', '', '100')
		self.H = self._add(grid, 'フレーム高さ H [mm]', '', '150')
		self.b = self._add(grid, '内幅 b [mm]', '', '80')
		self.h = self._add(grid, '内高さ h [mm]', '', '130')
		
		# 材料特性
		self.tensile = self._add(grid, '引張強さ [kg/cm²]', '', '410')
		self.yield_pt = self._add(grid, '降伏点 [kg/cm²]', '', '240')
		
		grid.AddGrowableCol(1, 1); grid.AddGrowableCol(3, 1)
		box = wx.StaticBoxSizer(wx.StaticBox(self, label='入力'), wx.VERTICAL)
		box.Add(grid, 0, wx.EXPAND | wx.ALL, 6)
		v.Add(box, 0, wx.EXPAND | wx.ALL, 6)
		
		# 計算・PDF出力ボタン
		row = wx.BoxSizer(wx.HORIZONTAL)
		btn_calc = wx.Button(self, label='計算')
		btn_pdf  = wx.Button(self, label='PDF出力')
		btn_pdf.Enable(False)
		row.Add(btn_calc, 0, wx.RIGHT, 8)
		row.Add(btn_pdf, 0)
		v.Add(row, 0, wx.ALIGN_CENTER | wx.ALL, 6)
		
		# 結果表示エリア
		self.result_text = wx.TextCtrl(self, style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_WORDWRAP)
		v.Add(self.result_text, 1, wx.EXPAND | wx.ALL, 6)
		
		# イベント
		btn_calc.Bind(wx.EVT_BUTTON, lambda e: (self.on_calc(), e.Skip()))
		btn_pdf.Bind(wx.EVT_BUTTON, lambda e: (self.on_export_pdf(), e.Skip()))
		self.btn_pdf = btn_pdf
		
		self.SetSizer(v)

	def _add(self, sizer, label, default='', hint=''):
		"""入力フィールド追加ヘルパー"""
		t = wx.TextCtrl(self, value=default, style=wx.TE_RIGHT)
		if hint:
			t.SetHint(hint)
		sizer.Add(wx.StaticText(self, label=label), 0, wx.ALIGN_CENTER_VERTICAL)
		sizer.Add(t, 0, wx.EXPAND)
		return t

	def on_calc(self):
		"""計算実行"""
		try:
			# 入力値取得
			W = float(self.W.GetValue() or 0)
			Wp = float(self.Wp.GetValue() or 0)
			L = float(self.L.GetValue() or 0)
			Lp = float(self.Lp.GetValue() or 0)
			Lf = float(self.Lf.GetValue() or 0)
			B = float(self.B.GetValue() or 0)
			H = float(self.H.GetValue() or 0)
			b = float(self.b.GetValue() or 0)
			h = float(self.h.GetValue() or 0)
			tensile = float(self.tensile.GetValue() or 0)
			yield_pt = float(self.yield_pt.GetValue() or 0)
			
			# 曲げモーメント計算（連結部での最大モーメント）
			M = W * 9.8 * L + Wp * 9.8 * Lp  # N·mm
			
			# 断面係数
			I = (B * H**3 - b * h**3) / 12.0  # mm^4
			Z = I / (H / 2.0)  # mm^3
			
			# 応力計算
			sigma = M / Z  # N/mm^2 = MPa
			sigma_kg_cm2 = sigma * 10.197  # kg/cm^2に変換
			
			# 安全率
			sf_yield = yield_pt / sigma_kg_cm2 if sigma_kg_cm2 > 0 else 0
			sf_tensile = tensile / sigma_kg_cm2 if sigma_kg_cm2 > 0 else 0
			
			# 判定
			if sf_yield >= 1.5:
				judgment = "○（安全率1.5以上確保）"
			elif sf_yield >= 1.0:
				judgment = "△（降伏点は超えないが安全率不足）"
			else:
				judgment = "×（降伏点を超える）"
			
			# 結果表示
			result = f"""【計算結果】

曲げモーメント: {M / 1000:.1f} N·m
断面係数 Z: {Z:.1f} mm³
発生応力: {sigma:.2f} MPa ({sigma_kg_cm2:.1f} kg/cm²)

降伏点: {yield_pt:.1f} kg/cm²
引張強さ: {tensile:.1f} kg/cm²

安全率（降伏点基準）: {sf_yield:.2f}
安全率（引張強さ基準）: {sf_tensile:.2f}

判定: {judgment}
"""
			
			self.result_text.SetValue(result)
			self.last = {
				'W': W, 'Wp': Wp, 'L': L, 'Lp': Lp, 'Lf': Lf,
				'B': B, 'H': H, 'b': b, 'h': h,
				'tensile': tensile, 'yield_pt': yield_pt,
				'M': M, 'Z': Z, 'sigma': sigma, 'sigma_kg_cm2': sigma_kg_cm2,
				'sf_yield': sf_yield, 'sf_tensile': sf_tensile,
				'judgment': judgment
			}
			self.btn_pdf.Enable(True)
			
		except ValueError as e:
			wx.MessageBox(f'入力値を確認してください: {e}', '入力エラー', wx.OK | wx.ICON_ERROR)
		except Exception as e:
			wx.MessageBox(f'計算エラー: {e}', 'エラー', wx.OK | wx.ICON_ERROR)

	def on_export_pdf(self):
		"""PDF出力"""
		if not self.last:
			wx.MessageBox('先に計算を実行してください。', '情報', wx.OK | wx.ICON_INFORMATION)
			return
		
		dlg = wx.FileDialog(self, 'PDF保存先を選択', wildcard='PDF files (*.pdf)|*.pdf',
		                    style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT)
		if dlg.ShowModal() != wx.ID_OK:
			dlg.Destroy()
			return
		path = dlg.GetPath()
		dlg.Destroy()
		
		try:
			self.export_to_path(path)
			wx.MessageBox(f'PDF出力完了:\n{path}', '完了', wx.OK | wx.ICON_INFORMATION)
		except Exception as e:
			wx.MessageBox(f'PDF出力エラー: {e}', 'エラー', wx.OK | wx.ICON_ERROR)

	def get_state(self):
		"""状態を取得"""
		return {
			'W': self.W.GetValue(),
			'Wp': self.Wp.GetValue(),
			'L': self.L.GetValue(),
			'Lp': self.Lp.GetValue(),
			'Lf': self.Lf.GetValue(),
			'B': self.B.GetValue(),
			'H': self.H.GetValue(),
			'b': self.b.GetValue(),
			'h': self.h.GetValue(),
			'tensile': self.tensile.GetValue(),
			'yield_pt': self.yield_pt.GetValue(),
			'result': self.result_text.GetValue(),
		}

	def set_state(self, state):
		"""状態を復元"""
		self.W.SetValue(state.get('W', ''))
		self.Wp.SetValue(state.get('Wp', ''))
		self.L.SetValue(state.get('L', ''))
		self.Lp.SetValue(state.get('Lp', ''))
		self.Lf.SetValue(state.get('Lf', ''))
		self.B.SetValue(state.get('B', ''))
		self.H.SetValue(state.get('H', ''))
		self.b.SetValue(state.get('b', ''))
		self.h.SetValue(state.get('h', ''))
		self.tensile.SetValue(state.get('tensile', ''))
		self.yield_pt.SetValue(state.get('yield_pt', ''))
		self.result_text.SetValue(state.get('result', ''))

	def export_to_path(self, path):
		"""PDF出力"""
		if not self.last:
			return
		
		from reportlab.pdfgen import canvas
		from reportlab.lib.pagesizes import A4
		from reportlab.pdfbase import pdfmetrics
		from reportlab.pdfbase.ttfonts import TTFont
		
		# 日本語フォント登録
		try:
			pdfmetrics.registerFont(TTFont('Japanese', 'C:\\Windows\\Fonts\\msgothic.ttc'))
			font_name = 'Japanese'
		except:
			font_name = 'Helvetica'
		
		c = canvas.Canvas(path, pagesize=A4)
		w, h = A4
		
		# タイトル
		c.setFont(font_name, 16)
		c.drawString(50, h - 50, '連結部フレーム強度計算書')
		
		y = h - 100
		c.setFont(font_name, 10)
		
		# 入力値
		c.drawString(50, y, '【入力条件】'); y -= 20
		c.drawString(70, y, f'最大積載量: {self.last["W"]:.0f} kg'); y -= 15
		c.drawString(70, y, f'装備品質量: {self.last["Wp"]:.0f} kg'); y -= 15
		c.drawString(70, y, f'連結中心から荷台中心: {self.last["L"]:.0f} mm'); y -= 15
		c.drawString(70, y, f'連結中心から装備品: {self.last["Lp"]:.0f} mm'); y -= 15
		c.drawString(70, y, f'フレーム長さ: {self.last["Lf"]:.0f} mm'); y -= 15
		c.drawString(70, y, f'断面寸法: B={self.last["B"]:.0f}, H={self.last["H"]:.0f}, b={self.last["b"]:.0f}, h={self.last["h"]:.0f} mm'); y -= 15
		c.drawString(70, y, f'材料: 引張強さ={self.last["tensile"]:.0f}, 降伏点={self.last["yield_pt"]:.0f} kg/cm²'); y -= 30
		
		# 計算結果
		c.drawString(50, y, '【計算結果】'); y -= 20
		c.drawString(70, y, f'曲げモーメント: {self.last["M"] / 1000:.1f} N·m'); y -= 15
		c.drawString(70, y, f'断面係数 Z: {self.last["Z"]:.1f} mm³'); y -= 15
		c.drawString(70, y, f'発生応力: {self.last["sigma"]:.2f} MPa ({self.last["sigma_kg_cm2"]:.1f} kg/cm²)'); y -= 15
		c.drawString(70, y, f'安全率（降伏点基準）: {self.last["sf_yield"]:.2f}'); y -= 15
		c.drawString(70, y, f'安全率（引張強さ基準）: {self.last["sf_tensile"]:.2f}'); y -= 15
		c.drawString(70, y, f'判定: {self.last["judgment"]}'); y -= 15
		
		c.save()

class HitchStrengthPanel(wx.Panel):
	"""ヒッチメンバー強度計算パネル"""
	def __init__(self, parent):
		super().__init__(parent)
		self.last = None
		v = wx.BoxSizer(wx.VERTICAL)
		
		# タイトル
		t = wx.StaticText(self, label='ヒッチメンバー強度計算')
		f = t.GetFont(); f.PointSize += 2; f = f.Bold(); t.SetFont(f)
		v.Add(t, 0, wx.ALL, 6)
		
		# 入力項目の位置イメージ（800px）
		img_path = os.path.join(os.path.dirname(__file__), 'assets', 'hitch_diagram.png')
		if os.path.exists(img_path):
			try:
				img = wx.Image(img_path, wx.BITMAP_TYPE_PNG)
				max_w = 800
				if img.GetWidth() > max_w:
					scale_h = int(img.GetHeight() * max_w / img.GetWidth())
					img = img.Scale(max_w, scale_h)
				bmp = wx.Bitmap(img)
				self.diagram = wx.StaticBitmap(self, bitmap=wx.BitmapBundle.FromBitmap(bmp))
				v.Add(self.diagram, 0, wx.ALIGN_CENTER | wx.ALL, 4)
			except Exception:
				pass
		
		# 入力フィールド
		grid = wx.FlexGridSizer(0, 4, 6, 8)
		
		# 荷重条件
		self.P = self._add(grid, '垂直荷重 P [kg]', '', '1500')
		self.H = self._add(grid, '水平牽引力 H [kg]', '', '300')
		
		# 寸法
		self.L = self._add(grid, 'ヒッチ有効長さ [mm]', '', '200')
		self.d = self._add(grid, '直径 or 辺長 [mm]', '', '50')
		
		# 材料形状
		self.material_type = wx.Choice(self)
		self.material_type.Append('円形')
		self.material_type.Append('角形')
		self.material_type.SetSelection(0)
		grid.Add(wx.StaticText(self, label='形状'), 0, wx.ALIGN_CENTER_VERTICAL)
		grid.Add(self.material_type, 0, wx.EXPAND)
		grid.Add(wx.StaticText(self), 0)
		grid.Add(wx.StaticText(self), 0)
		
		# 角形の場合の肉厚
		self.thickness = self._add(grid, '肉厚 (角形時) [mm]', '', '3')
		
		# 材料特性
		self.tensile = self._add(grid, '引張強さ [kg/cm²]', '', '410')
		self.yield_pt = self._add(grid, '降伏点 [kg/cm²]', '', '240')
		
		# 荷重倍率
		self.factor = self._add(grid, '荷重倍率', '', '2.5')
		
		grid.AddGrowableCol(1, 1); grid.AddGrowableCol(3, 1)
		box = wx.StaticBoxSizer(wx.StaticBox(self, label='入力'), wx.VERTICAL)
		box.Add(grid, 0, wx.EXPAND | wx.ALL, 6)
		v.Add(box, 0, wx.EXPAND | wx.ALL, 6)
		
		# 計算・PDF出力ボタン
		row = wx.BoxSizer(wx.HORIZONTAL)
		btn_calc = wx.Button(self, label='計算')
		btn_pdf  = wx.Button(self, label='PDF出力')
		btn_pdf.Enable(False)
		row.Add(btn_calc, 0, wx.RIGHT, 8)
		row.Add(btn_pdf, 0)
		v.Add(row, 0, wx.ALIGN_CENTER | wx.ALL, 6)
		
		# 結果表示エリア
		self.result_text = wx.TextCtrl(self, style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_WORDWRAP)
		v.Add(self.result_text, 1, wx.EXPAND | wx.ALL, 6)
		
		# イベント
		btn_calc.Bind(wx.EVT_BUTTON, lambda e: (self.on_calc(), e.Skip()))
		btn_pdf.Bind(wx.EVT_BUTTON, lambda e: (self.on_export_pdf(), e.Skip()))
		self.btn_pdf = btn_pdf
		
		self.SetSizer(v)

	def _add(self, sizer, label, default='', hint=''):
		"""入力フィールド追加ヘルパー"""
		t = wx.TextCtrl(self, value=default, style=wx.TE_RIGHT)
		if hint:
			t.SetHint(hint)
		sizer.Add(wx.StaticText(self, label=label), 0, wx.ALIGN_CENTER_VERTICAL)
		sizer.Add(t, 0, wx.EXPAND)
		return t

	def on_calc(self):
		"""計算実行"""
		try:
			# 入力値取得
			P = float(self.P.GetValue() or 0)
			H = float(self.H.GetValue() or 0)
			L = float(self.L.GetValue() or 0)
			d = float(self.d.GetValue() or 0)
			thickness = float(self.thickness.GetValue() or 0) if self.thickness.GetValue() else None
			tensile = float(self.tensile.GetValue() or 0)
			yield_pt = float(self.yield_pt.GetValue() or 0)
			factor = float(self.factor.GetValue() or 2.5)
			material_type = 'round' if self.material_type.GetSelection() == 0 else 'square'
			
			# 計算実行
			result = compute_hitch_strength(
				P=P, H=H, L_mm=L, d_mm=d,
				tensile_strength=tensile,
				yield_strength=yield_pt,
				thickness_mm=thickness,
				material_type=material_type,
				factor=factor
			)
			
			# 結果を整形表示
			result_str = format_hitch_strength_result(result)
			self.result_text.SetValue(result_str)
			
			# 結果保存
			self.last = result
			self.btn_pdf.Enable(True)
			
		except ValueError as e:
			wx.MessageBox(f'入力値を確認してください: {e}', '入力エラー', wx.OK | wx.ICON_ERROR)
		except Exception as e:
			wx.MessageBox(f'計算エラー: {e}', 'エラー', wx.OK | wx.ICON_ERROR)

	def on_export_pdf(self):
		"""PDF出力"""
		if not self.last:
			wx.MessageBox('先に計算を実行してください。', '情報', wx.OK | wx.ICON_INFORMATION)
			return
		
		dlg = wx.FileDialog(self, 'PDF保存先を選択', wildcard='PDF files (*.pdf)|*.pdf',
		                    style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT)
		if dlg.ShowModal() != wx.ID_OK:
			dlg.Destroy()
			return
		path = dlg.GetPath()
		dlg.Destroy()
		
		try:
			self.export_to_path(path)
			wx.MessageBox(f'PDF出力完了:\n{path}', '完了', wx.OK | wx.ICON_INFORMATION)
		except Exception as e:
			wx.MessageBox(f'PDF出力エラー: {e}', 'エラー', wx.OK | wx.ICON_ERROR)

	def get_state(self):
		"""状態を取得"""
		return {
			'P': self.P.GetValue(),
			'H': self.H.GetValue(),
			'L': self.L.GetValue(),
			'd': self.d.GetValue(),
			'thickness': self.thickness.GetValue(),
			'tensile': self.tensile.GetValue(),
			'yield_pt': self.yield_pt.GetValue(),
			'factor': self.factor.GetValue(),
			'material_type': self.material_type.GetSelection(),
			'result': self.result_text.GetValue(),
		}

	def set_state(self, state):
		"""状態を復元"""
		self.P.SetValue(state.get('P', ''))
		self.H.SetValue(state.get('H', ''))
		self.L.SetValue(state.get('L', ''))
		self.d.SetValue(state.get('d', ''))
		self.thickness.SetValue(state.get('thickness', ''))
		self.tensile.SetValue(state.get('tensile', ''))
		self.yield_pt.SetValue(state.get('yield_pt', ''))
		self.factor.SetValue(state.get('factor', ''))
		self.material_type.SetSelection(state.get('material_type', 0))
		self.result_text.SetValue(state.get('result', ''))

	def export_to_path(self, path):
		"""PDF出力"""
		if not self.last:
			return
		
		from reportlab.pdfgen import canvas
		from reportlab.lib.pagesizes import A4
		from reportlab.pdfbase import pdfmetrics
		from reportlab.pdfbase.ttfonts import TTFont
		
		# 日本語フォント登録
		try:
			pdfmetrics.registerFont(TTFont('Japanese', 'C:\\Windows\\Fonts\\msgothic.ttc'))
			font_name = 'Japanese'
		except:
			font_name = 'Helvetica'
		
		c = canvas.Canvas(path, pagesize=A4)
		w, h = A4
		
		# タイトル
		c.setFont(font_name, 16)
		c.drawString(50, h - 50, 'ヒッチメンバー強度計算書')
		
		y = h - 100
		c.setFont(font_name, 10)
		
		# 入力値
		c.drawString(50, y, '【入力条件】'); y -= 20
		c.drawString(70, y, f'垂直荷重 P: {self.last["P"]:.1f} kg'); y -= 15
		c.drawString(70, y, f'水平牽引力 H: {self.last["H"]:.1f} kg'); y -= 15
		c.drawString(70, y, f'有効長さ L: {self.last["L_mm"]:.1f} mm'); y -= 15
		c.drawString(70, y, f'荷重倍率: {self.last["factor"]:.1f}×'); y -= 15
		
		if self.last['material_type'] == 'round':
			c.drawString(70, y, f'形状: 円形 (直径 {self.last["d_mm"]:.1f} mm)'); y -= 15
		else:
			c.drawString(70, y, f'形状: 角形 (辺長 {self.last["d_mm"]:.1f} mm, 肉厚 {self.last["thickness_mm"]:.1f} mm)'); y -= 15
		
		c.drawString(70, y, f'材料: 引張強さ={self.last["tensile_strength"]:.1f}, 降伏点={self.last["yield_strength"]:.1f} kg/cm²'); y -= 30
		
		# 計算結果
		c.drawString(50, y, '【計算結果】'); y -= 20
		c.drawString(70, y, f'垂直曲げモーメント: {self.last["M_vertical"]:.1f} kg·cm'); y -= 15
		c.drawString(70, y, f'水平曲げモーメント: {self.last["M_horizontal"]:.1f} kg·cm'); y -= 15
		c.drawString(70, y, f'合成曲げモーメント: {self.last["M_combined"]:.1f} kg·cm'); y -= 15
		c.drawString(70, y, f'断面係数 Z: {self.last["Z"]:.3f} cm³'); y -= 15
		c.drawString(70, y, f'曲げ応力 σ: {self.last["sigma"]:.2f} kg/cm²'); y -= 15
		c.drawString(70, y, f'破断安全率: {self.last["sf_break"]:.2f}' + 
		            (' ✓ OK' if self.last['ok_break'] else ' ✗ NG') + 
		            f' (基準: > 1.6)'); y -= 15
		c.drawString(70, y, f'降伏安全率: {self.last["sf_yield"]:.2f}' + 
		            (' ✓ OK' if self.last['ok_yield'] else ' ✗ NG') + 
		            f' (基準: > 1.3)'); y -= 15
		
		c.save()

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
		
		# その他セクション
		self._add_section(scroll_sizer, "その他", scroll)
		notes_label = wx.StaticText(scroll, label="備考")
		scroll_sizer.Add(notes_label, 0, wx.ALL, 5)
		self.notes = wx.TextCtrl(scroll, style=wx.TE_MULTILINE, size=wx.Size(-1, 80))
		scroll_sizer.Add(self.notes, 0, wx.EXPAND|wx.LEFT|wx.RIGHT|wx.BOTTOM, 5)
		
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
			self.notes.SetValue("")
	
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
		data.notes = self.notes.GetValue()
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
			"",
			"【備考】",
			f"  {data.notes}",
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
			'notes': self.notes.GetValue(),
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
		if 'notes' in state:
			self.notes.SetValue(state['notes'])
	
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


class MainFrame(wx.Frame):
	def __init__(self):
		super().__init__(None,title='車両関連 統合計算ツール',size=wx.Size(1100,1000))
		
		# アイコン設定
		icon_path = 'app_icon.ico'
		if os.path.exists(icon_path):
			try:
				self.SetIcon(wx.Icon(icon_path, wx.BITMAP_TYPE_ICO))
			except Exception as e:
				print(f"アイコン読み込みエラー: {e}")
		
		self.nb=wx.Notebook(self, style=wx.NB_MULTILINE)
		self.panels = [
			('重量計算', WeightCalcPanel(self.nb)),
			('連結仕様', TrailerSpecPanel(self.nb)),
			('安定角度', StabilityAnglePanel(self.nb)),
			('旋回半径', TurningRadiusPanel(self.nb)),
			('車軸強度', AxleStrengthPanel(self.nb)),
			('車枠強度', FrameStrengthPanel(self.nb)),
			('連結部強度', CouplerStrengthPanel(self.nb)),
			('ヒッチメンバー強度', HitchStrengthPanel(self.nb)),
			('牽引車諸元', TowingSpecPanel(self.nb)),
			('板ばね分布', TwoAxleLeafSpringPanel(self.nb)),
			('安全チェーン', SafetyChainPanel(self.nb)),
			('保安基準適合検討表', Form2Panel(self.nb)),
			('1号様式', Form1Panel(self.nb)),
			('２号様式', OverviewPanel(self.nb)),
		]
		self.original_titles = [title for title, _ in self.panels]
		for title, panel in self.panels:
			self.nb.AddPage(panel, title)
		self.current_project_path = None
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
	app=wx.App(); frame=MainFrame(); frame.Show(); app.MainLoop()

if __name__=='__main__':
	main()
