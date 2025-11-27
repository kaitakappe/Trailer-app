import wx
import os
import tempfile
from typing import cast
try:
	from reportlab.pdfgen import canvas as _pdf_canvas
	from reportlab.lib.pagesizes import A4 as _A4
	from reportlab.pdfbase import pdfmetrics as _pdfmetrics
	from reportlab.pdfbase.ttfonts import TTFont as _TTFont
	_REPORTLAB_AVAILABLE = True
except ImportError:
	_REPORTLAB_AVAILABLE = False
from lib import (
	compute_weight_metrics,
	calc_braking_force, check_strength, calc_stability_angle,
	stop_distance, parking_brake_total, parking_brake_trailer, running_performance,
	calculate_stability_angle, calc_Lc, calc_R, compute_axle_strength, compute_frame_strength,
	compute_container_frame_strength, compute_container_frame_strength_axles,
	compute_frame_strength_hbeam, compute_container_frame_strength_hbeam, compute_container_frame_strength_axles_hbeam,
	compute_container_frame_strength_supports_inside, compute_container_frame_strength_supports_inside_hbeam
)

# 共通結果表示ウィンドウ (全パネルから利用) / 車枠強度グラフウィンドウ
RESULT_WINDOW = None
FRAME_GRAPH_WINDOW = None

class ResultWindow(wx.Frame):
	def __init__(self):
		super().__init__(None, title='計算結果', size=wx.Size(560, 620))
		self.txt = wx.TextCtrl(self, style=wx.TE_MULTILINE|wx.TE_READONLY|wx.VSCROLL)
		self.btn_copy = wx.Button(self, label='コピー')
		self.btn_close = wx.Button(self, label='閉じる')
		btn_row = wx.BoxSizer(wx.HORIZONTAL)
		btn_row.Add(self.btn_copy, 0, wx.RIGHT, 6)
		btn_row.Add(self.btn_close, 0)
		s = wx.BoxSizer(wx.VERTICAL)
		s.Add(btn_row, 0, wx.ALL|wx.ALIGN_RIGHT, 4)
		s.Add(self.txt, 1, wx.EXPAND|wx.ALL, 4)
		self.SetSizer(s)
		self.btn_copy.Bind(wx.EVT_BUTTON, self._on_copy)
		self.btn_close.Bind(wx.EVT_BUTTON, self._on_close_btn)
		self.Bind(wx.EVT_CLOSE, self._on_close_frame)

	def set_content(self, title: str, text: str):
		self.SetTitle(title)
		self.txt.SetValue(text)
		# 常に末尾を表示
		self.txt.ShowPosition(self.txt.GetLastPosition())

	def _on_copy(self, _):
		if wx.TheClipboard.Open():
			wx.TheClipboard.SetData(wx.TextDataObject(self.txt.GetValue()))
			wx.TheClipboard.Close()
			wx.MessageBox('結果をコピーしました。', 'コピー', wx.ICON_INFORMATION)

	def _on_close_btn(self, _):
		self.Close()

	def _on_close_frame(self, event):
		global RESULT_WINDOW
		RESULT_WINDOW = None
		event.Skip()

class FrameGraphWindow(wx.Frame):
	"""車枠強度 せん断力・曲げモーメント図専用ウィンドウ"""
	def __init__(self):
		super().__init__(None, title='車枠強度 図', size=wx.Size(780, 520))
		self.panel = wx.Panel(self)
		self.panel.Bind(wx.EVT_PAINT, self._on_paint)
		self.panel.Bind(wx.EVT_SIZE, lambda e: (e.Skip(), self.panel.Refresh()))
		self.data = None  # {'dists':[], 'shear_list':[], 'moment_list':[], 'Mmax': ...}
		self.status = wx.StatusBar(self)
		self.SetStatusBar(self.status)

	def set_data(self, data: dict):
		self.data = data
		self.status.SetStatusText(f"Mmax={data.get('Mmax','-')}  Z={data.get('Z_cm3','-')}cm³  σ={data.get('sigma','-')}kg/cm²")
		self.panel.Refresh()

	def _on_paint(self, event):
		dc = wx.BufferedPaintDC(self.panel)
		w, h = self.panel.GetClientSize()
		dc.SetBackground(wx.Brush(wx.Colour(255,255,255)))
		dc.Clear()
		margin = 50
		if not self.data:
			dc.SetTextForeground(wx.Colour(70,70,70))
			dc.DrawText('車枠強度計算後に図を表示します。', 20, 20)
			return
		dists = self.data['dists']
		shear_vals = self.data['shear_list']
		moment_vals = self.data['moment_list']
		positions = [0]
		for d in dists: positions.append(positions[-1] + d)
		L = positions[-1]
		if L <= 0:
			dc.DrawText('距離が0です', 10, 10); return
		x_scale = (w - 2*margin) / float(L)
		max_shear = max(abs(v) for v in shear_vals) if shear_vals else 1
		max_moment = max(abs(v) for v in moment_vals) if moment_vals else 1
		# レイアウト: せん断 (上 60%), モーメント (下 40%)
		shear_top = margin
		shear_bottom = int(margin + (h - 2*margin) * 0.60)
		moment_top = shear_bottom + 18
		moment_bottom = h - margin
		dc.SetPen(wx.Pen(wx.Colour(0,0,0),1))
		dc.DrawLine(margin, shear_bottom, w-margin, shear_bottom)
		dc.DrawLine(margin, moment_bottom, w-margin, moment_bottom)
		dc.SetFont(wx.Font(10, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD))
		dc.DrawText('せん断力 (kg)', margin, shear_top-22)
		dc.DrawText('曲げモーメント (kg·cm)', margin, moment_top-18)
		# 背景グリッド (せん断)
		grid_pen = wx.Pen(wx.Colour(225,225,225),1,style=wx.PENSTYLE_SHORT_DASH)
		dc.SetPen(grid_pen)
		for g in range(1,5):
			gy = int(shear_top + (shear_bottom - shear_top) * g / 5.0)
			dc.DrawLine(margin, gy, w-margin, gy)
		# せん断力プロット (ステップ線: 赤)
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
		# 曲げモーメント (棒: 青)
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
		dc.DrawText(f"Mmax={self.data['Mmax']:.1f}", w-margin-140, moment_top)
		dc.DrawText(f"Smax={max_shear:.1f}", w-margin-140, shear_top)
		dc.SetPen(wx.Pen(wx.Colour(185,185,185),1,style=wx.PENSTYLE_SHORT_DASH))
		dc.DrawRectangle(margin, shear_top, w-2*margin, shear_bottom - shear_top)
		dc.DrawRectangle(margin, moment_top, w-2*margin, moment_bottom - moment_top)
		dc.DrawText('赤:せん断力ステップ / 青:区間終端曲げモーメント', margin, h-24)

def show_frame_graph(data: dict):
	"""車枠強度グラフを別ウィンドウに表示/更新"""
	global FRAME_GRAPH_WINDOW
	if FRAME_GRAPH_WINDOW is None:
		FRAME_GRAPH_WINDOW = FrameGraphWindow()
	if not FRAME_GRAPH_WINDOW.IsShown():
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
	if RESULT_WINDOW is None:
		RESULT_WINDOW = ResultWindow()
	if not RESULT_WINDOW.IsShown():
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
	def __init__(self, parent):
		super().__init__(parent)
		v = wx.BoxSizer(wx.VERTICAL)
		self.vw = self._add(v, '車両重量 [kg]:', '2000')
		self.ml = self._add(v, '最大積載量 [kg]:', '1000')
		self.fa = self._add(v, '前軸重量 [kg]:', '1200')
		self.ra = self._add(v, '後軸重量 [kg]:', '1000')
		self.tc = self._add(v, 'タイヤ本数:', '4')
		self.tl = self._add(v, '推奨荷重/本 [kg]:', '600')
		self.cw = self._add(v, '接地幅/本 [cm]:', '18')
		# 追加: 前後軸タイヤサイズ入力
		self.ts_front = self._add(v, '前軸タイヤサイズ (インチ可):', '11R22.5')
		self.ts_rear = self._add(v, '後軸タイヤサイズ (インチ可):', '11R22.5')
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

	def _add(self, sizer, label, default=''):
		h = wx.BoxSizer(wx.HORIZONTAL)
		h.Add(wx.StaticText(self, label=label), 0, wx.RIGHT | wx.ALIGN_CENTER_VERTICAL, 6)
		t = wx.TextCtrl(self, value=default, style=wx.TE_RIGHT)
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
			for f in ['ipaexg.ttf', 'ipaexm.ttf', 'fonts/ipaexg.ttf', 'fonts/ipaexm.ttf']:
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
			for f in ['ipaexg.ttf', 'ipaexm.ttf', 'fonts/ipaexg.ttf', 'fonts/ipaexm.ttf']:
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
			c.showPage()
			c.save()
			_open_saved_pdf(path)
			wx.MessageBox('PDFを保存しました。', '完了', wx.ICON_INFORMATION)
		except Exception as e:
			wx.MessageBox(f'PDF出力中エラー: {e}', 'エラー', wx.ICON_ERROR)


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

		grid = wx.FlexGridSizer(0, 4, 6, 6)
		self.W = self._add(grid, '牽引車重量 W', '2000')
		self.Wp = self._add(grid, "トレーラ重量 W'", '800')
		self.Fm = self._add(grid, '牽引車制動力 Fm', '15000')
		self.Fmp = self._add(grid, "慣性制動力 Fm'", '8000')
		self.Fs = self._add(grid, '駐車制動力 Fs', '1200')
		self.Fsp = self._add(grid, "駐車制動力 Fs'", '500')
		self.WD = self._add(grid, '駆動軸重 WD', '1200')
		self.PS = self._add(grid, '最高出力 PS', '120')
		grid.AddGrowableCol(1, 1); grid.AddGrowableCol(3, 1)
		v = wx.BoxSizer(wx.VERTICAL)
		v.Add(info_sizer, 0, wx.EXPAND | wx.ALL, 6)
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

	def _add(self, sizer, label, default=''):
		sizer.Add(wx.StaticText(self, label=label), 0, wx.ALIGN_CENTER_VERTICAL)
		t = wx.TextCtrl(self, value=default, size=wx.Size(90, -1), style=wx.TE_RIGHT)
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
			for f in ['ipaexg.ttf','ipaexm.ttf','fonts/ipaexg.ttf','fonts/ipaexm.ttf']:
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
			('W1', '車両重量 W1 (kg)'),
			('W1f', '前軸重量 W1f (kg)'),
			('W1r', '後軸重量 W1r (kg)'),
			('T1f', '前輪輪距 T1f (m)'),
			('T1r', '後輪輪距(最外側) T1r (m)'),
			('H1', '重心高 H1 (m)'),
		]

		trailer_fields = [
			('W2', '車両重量 W2 (kg)'),
			('W2f', '第5輪重量 W2f (kg)'),
			('W2r', '後軸重量 W2r (kg)'),
			('T2f', 'キングピン安定幅 T2f (m)'),
			('T2r', '後輪輪距(最外側) T2r (m)'),
			('H2', '重心高 H2 (m)'),
		]

		for key, label in tractor_fields:
			tractor_grid.Add(wx.StaticText(self, label=label), 0, wx.ALIGN_CENTER_VERTICAL)
			t = wx.TextCtrl(self, value='0.0', size=wx.Size(90, -1), style=wx.TE_RIGHT)
			self.inputs[key] = t
			tractor_grid.Add(t, 0, wx.EXPAND)

		for key, label in trailer_fields:
			trailer_grid.Add(wx.StaticText(self, label=label), 0, wx.ALIGN_CENTER_VERTICAL)
			t = wx.TextCtrl(self, value='0.0', size=wx.Size(90, -1), style=wx.TE_RIGHT)
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
			w,h = _A4
			font='Helvetica'
			for f in ['ipaexg.ttf','ipaexm.ttf','fonts/ipaexg.ttf','fonts/ipaexm.ttf']:
				if os.path.exists(f):
					try:
						_pdfmetrics.registerFont(_TTFont('JPStab',f)); font='JPStab'; break
					except Exception: pass
			c.setFont(font,14)
			c.drawString(40,h-50,'最大安定傾斜角度計算書')
			c.setFont(font,9)
			# 入力諸元 (トラクタ / トレーラ)
			rows_tr = [
				['W1', f"{self.last_inputs['W1']:.1f}", 'kg', 'W1f', f"{self.last_inputs['W1f']:.1f}", 'kg'],
				['W1r', f"{self.last_inputs['W1r']:.1f}", 'kg', 'T1f', f"{self.last_inputs['T1f']:.3f}", 'm'],
				['T1r', f"{self.last_inputs['T1r']:.3f}", 'm', 'H1', f"{self.last_inputs['H1']:.3f}", 'm'],
			]
			rows_trl = [
				['W2', f"{self.last_inputs['W2']:.1f}", 'kg', 'W2f', f"{self.last_inputs['W2f']:.1f}", 'kg'],
				['W2r', f"{self.last_inputs['W2r']:.1f}", 'kg', 'T2f', f"{self.last_inputs['T2f']:.3f}", 'm'],
				['T2r', f"{self.last_inputs['T2r']:.3f}", 'm', 'H2', f"{self.last_inputs['H2']:.3f}", 'm'],
			]
			cw=[45,55,35,45,55,35]
			def table(x,y,cw,rh,data,title):
				Wsum=sum(cw); Ht=rh*(len(data)+1); c.rect(x,y-Ht,Wsum,Ht)
				c.setFont(font,10); c.drawString(x+4,y-14,title); c.setFont(font,9)
				c.line(x,y-rh,x+Wsum,y-rh)
				cx=x
				for wcol in cw[:-1]: cx+=wcol; c.line(cx,y,cx,y-Ht)
				for r,row in enumerate(data):
					for j,cell in enumerate(row): c.drawString(x+5+sum(cw[:j]), y-rh*(r+2)+4, cell)
				return y-Ht-20
			start_y=h-90
			next_y=table(40,start_y,cw,16,rows_tr,'トラクタ諸元')
			next_y=table(40,next_y,cw,16,rows_trl,'トレーラ諸元')
			# 計算結果
			B1=self.last_res.get('B1',0); B2=self.last_res.get('B2',0); B=self.last_res.get('B',0); Hc=self.last_res.get('H',0); theta=self.last_res.get('theta1',0)
			c.setFont(font,11); c.drawString(40,next_y,'(1) 計算結果')
			c.setFont(font,9)
			c.drawString(55,next_y-16,f"B1 = {B1:.4f} m  B2 = {B2:.4f} m  B = {B:.4f} m")
			c.drawString(55,next_y-30,f"H = {Hc:.4f} m  θ1 = {theta:.4f}°")
			# 式展開
			y = next_y-60
			W1=self.last_inputs['W1']; W1f=self.last_inputs['W1f']; W1r=self.last_inputs['W1r']; T1f=self.last_inputs['T1f']; T1r=self.last_inputs['T1r']; H1=self.last_inputs['H1']
			W2=self.last_inputs['W2']; W2f=self.last_inputs['W2f']; W2r=self.last_inputs['W2r']; T2f=self.last_inputs['T2f']; T2r=self.last_inputs['T2r']; H2=self.last_inputs['H2']
			c.setFont(font,11); c.drawString(40,y,'(2) 計算式展開')
			c.setFont(font,9)
			c.drawString(55,y-14,f"B1 = (W1f×T1f + W1r×T1r)/(2×W1) = ({W1f:.1f}×{T1f:.3f} + {W1r:.1f}×{T1r:.3f})/(2×{W1:.1f}) = {B1:.4f} m")
			c.drawString(55,y-28,f"B2 = (W2f×T2f + W2r×T2r)/(2×W2) = ({W2f:.1f}×{T2f:.3f} + {W2r:.1f}×{T2r:.3f})/(2×{W2:.1f}) = {B2:.4f} m")
			c.drawString(55,y-42,f"B  = (W1×B1 + W2×B2)/(W1+W2) = ({W1:.1f}×{B1:.4f} + {W2:.1f}×{B2:.4f})/({W1:.1f}+{W2:.1f}) = {B:.4f} m")
			c.drawString(55,y-56,f"H  = (H1×W1 + H2×W2)/(W1+W2) = ({H1:.3f}×{W1:.1f} + {H2:.3f}×{W2:.1f})/({W1:.1f}+{W2:.1f}) = {Hc:.4f} m")
			c.drawString(55,y-70,f"tan θ1 = B/H = {B:.4f}/{Hc:.4f} → θ1 = {theta:.4f}°")
			c.showPage(); c.save(); _open_saved_pdf(path); wx.MessageBox('PDFを保存しました。', '完了', wx.ICON_INFORMATION)
		except Exception as e:
			wx.MessageBox(f'PDF出力中エラー: {e}', 'エラー', wx.ICON_ERROR)


class ChassisFramePanel(wx.Panel):
	def __init__(self,parent):
		# 廃止: シャーシ強度計算パネルは未使用。型解析エラー抑止用に最低限属性定義。
		super().__init__(parent)
		self.last=None
		self.load_sizer = wx.FlexGridSizer(0,2,4,4)
		self.point_load_ctrls = []
		self.pos_ctrls = []
		self.load_count = wx.SpinCtrl(self, min=0, max=10, initial=0)

	def _row(self,sizer,label,default):
		h = wx.BoxSizer(wx.HORIZONTAL)
		h.Add(wx.StaticText(self,label=label),0,wx.RIGHT|wx.ALIGN_CENTER_VERTICAL,6)
		ctrl = wx.TextCtrl(self,value=default,size=wx.Size(90,-1),style=wx.TE_RIGHT)
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
			pl = wx.TextCtrl(self,value='300',size=wx.Size(70,-1),style=wx.TE_RIGHT); self.point_load_ctrls.append(pl); self.load_sizer.Add(pl,0)
			self.load_sizer.Add(wx.StaticText(self,label=f'位置{i+1}(mm)'),0,wx.ALIGN_CENTER_VERTICAL)
			pos = wx.TextCtrl(self,value=str(1000*(i+1)),size=wx.Size(70,-1),style=wx.TE_RIGHT); self.pos_ctrls.append(pos); self.load_sizer.Add(pos,0)
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
		self.L1 = self._add(tractor_s, '軸距 L1 [m]', '3.450')
		self.i1_input = self._add(tractor_s, '前輪給距の 1/2 値 I1 [m]', '1.030')
		# 派生値 I1 (Trf1/2) を表示用に追加（読み取り専用, m単位）
		row1 = wx.BoxSizer(wx.HORIZONTAL)
		row1.Add(wx.StaticText(self, label='前輪給距の 1/2 値 I1 [m]'), 0, wx.RIGHT | wx.ALIGN_CENTER_VERTICAL, 6)
		self.i1_disp = wx.TextCtrl(self, value='1.030', style=wx.TE_RIGHT | wx.TE_READONLY)
		row1.Add(self.i1_disp, 0)
		tractor_s.Add(row1, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, 4)

		trailer_box = wx.StaticBox(self, label='(2) トレーラ諸元')
		trailer_s = wx.StaticBoxSizer(trailer_box, wx.VERTICAL)
		self.L2 = self._add(trailer_s, '軸距 L2 [m]', '8.870')
		self.i2_input = self._add(trailer_s, '後輪給距の 1/2 値 I2 [m]', '0.930')
		# 派生値 I2 (Trf2/2) を表示用に追加（読み取り専用, m単位）
		row2 = wx.BoxSizer(wx.HORIZONTAL)
		row2.Add(wx.StaticText(self, label='後輪給距の 1/2 値 I2 [m]'), 0, wx.RIGHT | wx.ALIGN_CENTER_VERTICAL, 6)
		self.i2_disp = wx.TextCtrl(self, value='0.930', style=wx.TE_RIGHT | wx.TE_READONLY)
		row2.Add(self.i2_disp, 0)
		trailer_s.Add(row2, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, 4)

		# 共通: カプラオフセット S と ハンドル切れ角 θ
		self.S = self._add(v, 'カプラオフセット S [m]', '0.650')
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

	def _add(self,sizer,label,default=''):
		h=wx.BoxSizer(wx.HORIZONTAL)
		h.Add(wx.StaticText(self,label=label),0,wx.RIGHT|wx.ALIGN_CENTER_VERTICAL,6)
		t=wx.TextCtrl(self,value=default,style=wx.TE_RIGHT); h.Add(t,1)
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
			for f in ['ipaexg.ttf','ipaexm.ttf','fonts/ipaexg.ttf','fonts/ipaexm.ttf']:
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
				['前輪給距の 1/2 値 I1', f"{I1:.3f}", 'm'],
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
				['後輪給距の 1/2 値 I2', f"{I2:.3f}", 'm'],
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
		self.W = self._add(v, '車両総重量 W [kg]:', '4000')
		self.wheels = self._add(v, '車輪数 n:', '2')
		self.d = self._add(v, '車軸径 d [mm]:', '60')
		self.deltaS = self._add(v, '軸中心～軸受中心距離 ΔS [mm]:', '500')
		self.tensile = self._add(v, '引張強さ θb [kg/cm²]:', '55')
		self.yield_pt = self._add(v, '降伏点 θy [kg/cm²]:', '40')
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
			for f in ['ipaexg.ttf','ipaexm.ttf','fonts/ipaexg.ttf','fonts/ipaexm.ttf']:
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
			c.showPage(); c.save(); wx.MessageBox('PDFを保存しました。','完了',wx.ICON_INFORMATION)
		except Exception as e:
			wx.MessageBox(f'PDF出力中エラー: {e}', 'エラー', wx.ICON_ERROR)


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
			ctrl=wx.TextCtrl(self.legacy_panel,value='50',size=wx.Size(70,-1),style=wx.TE_RIGHT); self.loads.append(ctrl); grid_load.Add(ctrl,0)
			grid_load.Add(wx.Size(10,10)) if i%2==0 else None
		box_load=wx.StaticBoxSizer(wx.StaticBox(self.legacy_panel,label='荷重入力 (6点)'),wx.VERTICAL)
		box_load.Add(grid_load,0,wx.EXPAND|wx.ALL,4); legacy_s.Add(box_load,0,wx.EXPAND|wx.ALL,4)
		self.dists=[]
		grid_dist=wx.FlexGridSizer(0,2,4,6)
		for i in range(5):
			grid_dist.Add(wx.StaticText(self.legacy_panel,label=f'距離{i+1}(mm)'),0,wx.ALIGN_CENTER_VERTICAL)
			dc=wx.TextCtrl(self.legacy_panel,value='500',size=wx.Size(70,-1),style=wx.TE_RIGHT); self.dists.append(dc); grid_dist.Add(dc,0)
		box_dist=wx.StaticBoxSizer(wx.StaticBox(self.legacy_panel,label='区間距離 (5区間)'),wx.VERTICAL)
		box_dist.Add(grid_dist,0,wx.EXPAND|wx.ALL,4); legacy_s.Add(box_dist,0,wx.EXPAND|wx.ALL,4)
		self.legacy_panel.SetSizer(legacy_s); v.Add(self.legacy_panel,0,wx.EXPAND|wx.ALL,4)
		# コンテナ4点座 × 支点2点(荷重間) モード入力
		self.container_panel = wx.Panel(self)
		cont_s = wx.BoxSizer(wx.VERTICAL)
		grid_cont = wx.FlexGridSizer(0,2,4,6)
		self.ct_weight = wx.TextCtrl(self.container_panel,value='2800',style=wx.TE_RIGHT)
		self.ct_span = wx.TextCtrl(self.container_panel,value='6000',style=wx.TE_RIGHT)
		self.ct_coupler_offset = wx.TextCtrl(self.container_panel,value='800',style=wx.TE_RIGHT)
		self.ct_coupler_offset.SetToolTip('連結部(カプラ)から縦桁前端までの距離')
		self.ct_front_off = wx.TextCtrl(self.container_panel,value='600',style=wx.TE_RIGHT)
		self.ct_rear_off = wx.TextCtrl(self.container_panel,value='600',style=wx.TE_RIGHT)
		self.ct_axle1 = wx.TextCtrl(self.container_panel,value='2400',style=wx.TE_RIGHT)
		self.ct_axle1.SetToolTip('サスペンションハンガー中心位置 (前側支点)')
		self.ct_axle2 = wx.TextCtrl(self.container_panel,value='3600',style=wx.TE_RIGHT)
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
		self.B=self._dim(rect_s,'外側全幅 B (mm)','50',parent=self.rect_panel); self.H=self._dim(rect_s,'外側全高さ H (mm)','102',parent=self.rect_panel)
		self.b=self._dim(rect_s,'内空部幅 b (mm)','38',parent=self.rect_panel); self.h=self._dim(rect_s,'内空部高さ h (mm)','90',parent=self.rect_panel)
		self.rect_panel.SetSizer(rect_s); v.Add(self.rect_panel,0,wx.EXPAND|wx.ALL,4)
		# 断面寸法パネル: H形鋼
		self.hbeam_panel = wx.Panel(self)
		hb_s = wx.BoxSizer(wx.VERTICAL)
		self.B_h=self._dim(hb_s,'フランジ幅 B (mm)','150',parent=self.hbeam_panel); self.H_h=self._dim(hb_s,'全高さ H (mm)','200',parent=self.hbeam_panel)
		self.tw_h=self._dim(hb_s,'ウェブ厚 tw (mm)','8',parent=self.hbeam_panel); self.tf_h=self._dim(hb_s,'フランジ厚 tf (mm)','12',parent=self.hbeam_panel)
		self.hbeam_panel.SetSizer(hb_s); v.Add(self.hbeam_panel,0,wx.EXPAND|wx.ALL,4)
		# 材料
		self.tensile=self._dim(v,'引張強さ θb (kg/cm²)','410'); self.yield_pt=self._dim(v,'降伏点 θy (kg/cm²)','240')
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
			for f in ['ipaexg.ttf','ipaexm.ttf','fonts/ipaexg.ttf','fonts/ipaexm.ttf']:
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
						img_w=450; img_h=140
						c.drawImage(seating_diagram, left, y-img_h, width=img_w, height=img_h, preserveAspectRatio=True, mask='auto')
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
					img_w=130; img_h=130
					c.drawImage(cross_diagram, left, y-img_h, width=img_w, height=img_h, preserveAspectRatio=True, mask='auto')
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

	def _dim(self, sizer, label, default, parent=None):
		# sizer が紐づくコンテナ (Panel) を親として部品生成することで
		# SetSizer されたパネルと子ウィンドウ親が一致し wxSizer のアサートを防ぐ。
		if parent is None:
			parent = getattr(sizer, 'GetContainingWindow', lambda: None)() or self
		h = wx.BoxSizer(wx.HORIZONTAL)
		h.Add(wx.StaticText(parent,label=label),0,wx.RIGHT|wx.ALIGN_CENTER_VERTICAL,6)
		ctrl = wx.TextCtrl(parent,value=default,size=wx.Size(80,-1),style=wx.TE_RIGHT)
		h.Add(ctrl,0)
		sizer.Add(h,0,wx.EXPAND|wx.LEFT|wx.RIGHT|wx.TOP,4)
		return ctrl



class CouplerStrengthPanel(wx.Panel):
	"""連結部フレーム強度計算パネル"""
	def __init__(self, parent):
		super().__init__(parent)
		self.last = {}
		
		# メインレイアウト
		main_sizer = wx.BoxSizer(wx.VERTICAL)
		
		# タイトル
		title = wx.StaticText(self, label='連結部フレーム強度計算')
		title_font = title.GetFont()
		title_font.PointSize += 3
		title_font = title_font.Bold()
		title.SetFont(title_font)
		main_sizer.Add(title, 0, wx.ALL, 10)
		
		# 入力セクション
		input_box = wx.StaticBoxSizer(wx.VERTICAL, self, '入力条件')
		
		# 荷重条件
		load_label = wx.StaticText(self, label='荷重条件')
		load_font = load_label.GetFont().Bold()
		load_label.SetFont(load_font)
		input_box.Add(load_label, 0, wx.ALL, 5)
		
		grid1 = wx.FlexGridSizer(3, 4, 5, 10)
		grid1.Add(wx.StaticText(self, label='トレーラ総重量'), 0, wx.ALIGN_CENTER_VERTICAL)
		self.ct_total_weight = wx.TextCtrl(self, value='3500', style=wx.TE_RIGHT)
		grid1.Add(self.ct_total_weight, 0, wx.EXPAND)
		grid1.Add(wx.StaticText(self, label='kg'), 0, wx.ALIGN_CENTER_VERTICAL)
		grid1.Add(wx.StaticText(self, label=''), 0)
		
		grid1.Add(wx.StaticText(self, label='牽引負荷'), 0, wx.ALIGN_CENTER_VERTICAL)
		self.ct_tow_load = wx.TextCtrl(self, value='500', style=wx.TE_RIGHT)
		grid1.Add(self.ct_tow_load, 0, wx.EXPAND)
		grid1.Add(wx.StaticText(self, label='kg'), 0, wx.ALIGN_CENTER_VERTICAL)
		grid1.Add(wx.StaticText(self, label='(水平牽引時)'), 0, wx.ALIGN_CENTER_VERTICAL)
		
		grid1.Add(wx.StaticText(self, label='安全率'), 0, wx.ALIGN_CENTER_VERTICAL)
		self.ct_safety_factor = wx.TextCtrl(self, value='2.5', style=wx.TE_RIGHT)
		grid1.Add(self.ct_safety_factor, 0, wx.EXPAND)
		grid1.Add(wx.StaticText(self, label=''), 0, wx.ALIGN_CENTER_VERTICAL)
		grid1.Add(wx.StaticText(self, label=''), 0)
		
		input_box.Add(grid1, 0, wx.ALL|wx.EXPAND, 5)
		
		# 鋼材寸法
		dim_label = wx.StaticText(self, label='鋼材寸法 (矩形鋼管)')
		dim_label.SetFont(load_font)
		input_box.Add(dim_label, 0, wx.ALL, 5)
		
		grid2 = wx.FlexGridSizer(2, 4, 5, 10)
		grid2.Add(wx.StaticText(self, label='外径 B'), 0, wx.ALIGN_CENTER_VERTICAL)
		self.ct_B = wx.TextCtrl(self, value='100', style=wx.TE_RIGHT)
		grid2.Add(self.ct_B, 0, wx.EXPAND)
		grid2.Add(wx.StaticText(self, label='mm'), 0, wx.ALIGN_CENTER_VERTICAL)
		grid2.Add(wx.StaticText(self, label='(幅)'), 0, wx.ALIGN_CENTER_VERTICAL)
		
		grid2.Add(wx.StaticText(self, label='外径 H'), 0, wx.ALIGN_CENTER_VERTICAL)
		self.ct_H = wx.TextCtrl(self, value='100', style=wx.TE_RIGHT)
		grid2.Add(self.ct_H, 0, wx.EXPAND)
		grid2.Add(wx.StaticText(self, label='mm'), 0, wx.ALIGN_CENTER_VERTICAL)
		grid2.Add(wx.StaticText(self, label='(高さ)'), 0, wx.ALIGN_CENTER_VERTICAL)
		
		input_box.Add(grid2, 0, wx.ALL|wx.EXPAND, 5)
		
		grid3 = wx.FlexGridSizer(2, 4, 5, 10)
		grid3.Add(wx.StaticText(self, label='内径 b'), 0, wx.ALIGN_CENTER_VERTICAL)
		self.ct_b = wx.TextCtrl(self, value='90', style=wx.TE_RIGHT)
		grid3.Add(self.ct_b, 0, wx.EXPAND)
		grid3.Add(wx.StaticText(self, label='mm'), 0, wx.ALIGN_CENTER_VERTICAL)
		grid3.Add(wx.StaticText(self, label='(幅)'), 0, wx.ALIGN_CENTER_VERTICAL)
		
		grid3.Add(wx.StaticText(self, label='内径 h'), 0, wx.ALIGN_CENTER_VERTICAL)
		self.ct_h = wx.TextCtrl(self, value='90', style=wx.TE_RIGHT)
		grid3.Add(self.ct_h, 0, wx.EXPAND)
		grid3.Add(wx.StaticText(self, label='mm'), 0, wx.ALIGN_CENTER_VERTICAL)
		grid3.Add(wx.StaticText(self, label='(高さ)'), 0, wx.ALIGN_CENTER_VERTICAL)
		
		input_box.Add(grid3, 0, wx.ALL|wx.EXPAND, 5)
		
		# 材料強度
		mat_label = wx.StaticText(self, label='材料強度')
		mat_label.SetFont(load_font)
		input_box.Add(mat_label, 0, wx.ALL, 5)
		
		grid4 = wx.FlexGridSizer(2, 4, 5, 10)
		grid4.Add(wx.StaticText(self, label='引張強さ θb'), 0, wx.ALIGN_CENTER_VERTICAL)
		self.ct_tb = wx.TextCtrl(self, value='4100', style=wx.TE_RIGHT)
		grid4.Add(self.ct_tb, 0, wx.EXPAND)
		grid4.Add(wx.StaticText(self, label='kg/cm²'), 0, wx.ALIGN_CENTER_VERTICAL)
		grid4.Add(wx.StaticText(self, label='(SS400: 4100)'), 0, wx.ALIGN_CENTER_VERTICAL)
		
		grid4.Add(wx.StaticText(self, label='降伏点 θy'), 0, wx.ALIGN_CENTER_VERTICAL)
		self.ct_ty = wx.TextCtrl(self, value='2400', style=wx.TE_RIGHT)
		grid4.Add(self.ct_ty, 0, wx.EXPAND)
		grid4.Add(wx.StaticText(self, label='kg/cm²'), 0, wx.ALIGN_CENTER_VERTICAL)
		grid4.Add(wx.StaticText(self, label='(SS400: 2400)'), 0, wx.ALIGN_CENTER_VERTICAL)
		
		input_box.Add(grid4, 0, wx.ALL|wx.EXPAND, 5)
		
		main_sizer.Add(input_box, 0, wx.ALL|wx.EXPAND, 10)
		
		# ボタン
		btn_sizer = wx.BoxSizer(wx.HORIZONTAL)
		self.btn_calc = wx.Button(self, label='計算実行')
		self.btn_export = wx.Button(self, label='PDF出力')
		self.btn_export.Enable(False)
		btn_sizer.Add(self.btn_calc, 0, wx.RIGHT, 10)
		btn_sizer.Add(self.btn_export, 0)
		main_sizer.Add(btn_sizer, 0, wx.ALL|wx.ALIGN_CENTER, 10)
		
		# 説明
		note = wx.StaticText(self, label='※連結部の引張強度を計算します。牽引負荷と材料強度から安全性を判定します。')
		note.SetForegroundColour(wx.Colour(100, 100, 100))
		main_sizer.Add(note, 0, wx.ALL, 10)
		
		self.SetSizer(main_sizer)
		
		# イベント
		self.btn_calc.Bind(wx.EVT_BUTTON, self.on_calc)
		self.btn_export.Bind(wx.EVT_BUTTON, self.on_export_pdf)
	
	def on_calc(self, event):
		try:
			# 入力取得
			total_weight = float(self.ct_total_weight.GetValue())
			tow_load = float(self.ct_tow_load.GetValue())
			safety_factor = float(self.ct_safety_factor.GetValue())
			B = float(self.ct_B.GetValue())
			H = float(self.ct_H.GetValue())
			b = float(self.ct_b.GetValue())
			h = float(self.ct_h.GetValue())
			tb = float(self.ct_tb.GetValue())
			ty = float(self.ct_ty.GetValue())
			
			# 断面積計算 (矩形鋼管)
			A = (B * H - b * h) / 100.0  # mm² -> cm²
			
			# 引張力 (kg)
			P = tow_load
			
			# 引張応力 (kg/cm²)
			sigma = P / A if A > 0 else 0
			
			# 安全率
			sf_break = tb / (safety_factor * sigma) if sigma > 0 else float('inf')
			sf_yield = ty / (safety_factor * sigma) if sigma > 0 else float('inf')
			
			# 判定
			ok_break = sf_break >= 1.0
			ok_yield = sf_yield >= 1.0
			
			# 結果保存
			self.last = {
				'total_weight': total_weight,
				'tow_load': tow_load,
				'safety_factor': safety_factor,
				'B': B, 'H': H, 'b': b, 'h': h,
				'tb': tb, 'ty': ty,
				'A': A,
				'P': P,
				'sigma': sigma,
				'sf_break': sf_break,
				'sf_yield': sf_yield,
				'ok_break': ok_break,
				'ok_yield': ok_yield
			}
			
			# 結果表示
			result_text = f"""【連結部フレーム強度計算結果】

■入力条件
トレーラ総重量: {total_weight:.1f} kg
牽引負荷: {tow_load:.1f} kg
安全率: {safety_factor:.1f}

■鋼材寸法 (矩形鋼管)
外径: B={B:.1f} mm × H={H:.1f} mm
内径: b={b:.1f} mm × h={h:.1f} mm
断面積: A={A:.2f} cm²

■材料強度
引張強さ θb: {tb:.1f} kg/cm²
降伏点 θy: {ty:.1f} kg/cm²

■計算結果
引張力: P={P:.1f} kg
引張応力: σ={sigma:.2f} kg/cm²

破断安全率: {sf_break:.3f} {'(OK)' if ok_break else '(NG)'}
降伏安全率: {sf_yield:.3f} {'(OK)' if ok_yield else '(NG)'}

■総合判定: {'基準を満たす' if (ok_break and ok_yield) else '基準を満たさない'}

※計算式:
  断面積 A = (B×H - b×h) / 100  [cm²]
  引張応力 σ = P / A  [kg/cm²]
  破断安全率 = θb / (安全率 × σ)
  降伏安全率 = θy / (安全率 × σ)
"""
			
			global RESULT_WINDOW
			if RESULT_WINDOW is None:
				RESULT_WINDOW = ResultWindow()
			RESULT_WINDOW.set_content('連結部強度計算結果', result_text)
			RESULT_WINDOW.Show()
			RESULT_WINDOW.Raise()
			
			self.btn_export.Enable(True)
			
		except ValueError as e:
			wx.MessageBox(f'入力値エラー: {e}', 'エラー', wx.ICON_ERROR)
		except Exception as e:
			wx.MessageBox(f'計算エラー: {e}', 'エラー', wx.ICON_ERROR)
	
	def on_export_pdf(self, event):
		if not self.last:
			wx.MessageBox('先に計算を実行してください。', '情報', wx.ICON_INFORMATION)
			return
		
		if not _REPORTLAB_AVAILABLE:
			wx.MessageBox('ReportLabがインストールされていません。\npip install reportlab', 'エラー', wx.ICON_ERROR)
			return
		
		dlg = wx.FileDialog(self, 'PDF保存', defaultFile='車枠強度検討書(連結部フレーム).pdf',
							wildcard='PDF files (*.pdf)|*.pdf',
							style=wx.FD_SAVE|wx.FD_OVERWRITE_PROMPT)
		if dlg.ShowModal() != wx.ID_OK:
			return
		
		path = dlg.GetPath()
		dlg.Destroy()
		
		try:
			self._generate_pdf(path)
			wx.MessageBox(f'PDFを保存しました:\n{path}', '完了', wx.ICON_INFORMATION)
			self._open_saved_pdf(path)
		except Exception as e:
			wx.MessageBox(f'PDF生成エラー: {e}', 'エラー', wx.ICON_ERROR)
	
	def _open_saved_pdf(self, path: str):
		try:
			import subprocess
			if os.name == 'nt':
				os.startfile(path)
			elif os.name == 'posix':
				subprocess.call(['open', path])
		except Exception:
			pass
	
	def _generate_pdf(self, path: str):
		from reportlab.pdfgen import canvas as pdf_canvas
		from reportlab.lib.pagesizes import A4
		from reportlab.pdfbase import pdfmetrics
		from reportlab.pdfbase.ttfonts import TTFont
		
		# フォント設定
		W, H = A4
		c = pdf_canvas.Canvas(path, pagesize=A4)
		font = 'HeiseiKakuGo-W5'
		# 日本語フォント登録試行
		for f in [r'C:\Windows\Fonts\msgothic.ttc', r'C:\Windows\Fonts\msmincho.ttc']:
			if os.path.exists(f):
				try:
					pdfmetrics.registerFont(TTFont('JPFrame', f))
					font = 'JPFrame'
					break
				except Exception:
					pass
		
		v = self.last
		left = 40; right = 40; top = 40; bottom = 50
		y = H - top
		
		# タイトル
		c.setFont(font, 13)
		c.drawString(left, y, '連結部フレーム強度計算書')
		y -= 18
		c.setFont(font, 9)
		
		# 断面図生成
		cross_diagram = ''
		try:
			cross_diagram = create_cross_section_diagram_png(
				v['B'], v['H'], v['b'], v['h'], 0, 0, 'rect', width=250, height=250
			)
		except Exception:
			pass
		
		# ヘルパー関数
		def ensure_space(h_needed):
			nonlocal y
			if y - h_needed < bottom:
				c.showPage()
				c.setFont(font, 9)
				y = H - top
		
		def section(title: str, gap: int=8):
			nonlocal y
			ensure_space(20)
			c.setFont(font, 10)
			c.drawString(left, y, title)
			y -= gap + 4
			c.setFont(font, 9)
		
		def simple_table(rows: list[tuple[str,str,str]], colw=(160,95,65), row_h=18):
			nonlocal y
			Wtot = sum(colw); Ht = row_h * len(rows)
			ensure_space(Ht + 8)
			c.rect(left, y - Ht, Wtot, Ht)
			for i in range(1, len(rows)):
				c.line(left, y - row_h * i, left + Wtot, y - row_h * i)
			cx = left
			for wcol in colw[:-1]:
				cx += wcol
				c.line(cx, y, cx, y - Ht)
			for r, (lab, val, unit) in enumerate(rows):
				cy = y - row_h * (r + 1) + 7
				c.drawString(left + 4, cy, lab)
				c.drawRightString(left + colw[0] + colw[1] - 6, cy, val)
				c.drawString(left + colw[0] + colw[1] + 4, cy, unit)
			y -= Ht + 12
		
		# 入力条件
		section('入力条件')
		simple_table([
			('トレーラ総重量', f"{v['total_weight']:.1f}", 'kg'),
			('牽引負荷', f"{v['tow_load']:.1f}", 'kg'),
			('安全率', f"{v['safety_factor']:.1f}", ''),
		])		# 鋼材寸法
		section('鋼材寸法 (矩形鋼管)')
		simple_table([
			('外径 B', f"{v['B']:.1f}", 'mm'),
			('外径 H', f"{v['H']:.1f}", 'mm'),
			('内径 b', f"{v['b']:.1f}", 'mm'),
			('内径 h', f"{v['h']:.1f}", 'mm'),
			('断面積 A', f"{v['A']:.2f}", 'cm²'),
		])
		
		# 断面図を挿入
		if cross_diagram:
			try:
				section('断面図')
				ensure_space(160)
				img_w = 150; img_h = 150
				c.drawImage(cross_diagram, left, y - img_h, width=img_w, height=img_h, 
						   preserveAspectRatio=True, mask='auto')
				y -= img_h + 10
			except Exception:
				pass
		
		# 材料強度
		section('材料強度')
		simple_table([
			('引張強さ θb', f"{v['tb']:.1f}", 'kg/cm²'),
			('降伏点 θy', f"{v['ty']:.1f}", 'kg/cm²'),
		])
		
		# 計算結果
		section('計算結果')
		simple_table([
			('引張力 P', f"{v['P']:.1f}", 'kg'),
			('引張応力 σ', f"{v['sigma']:.2f}", 'kg/cm²'),
			('破断安全率', f"{v['sf_break']:.3f}", '(OK)' if v['ok_break'] else '(NG)'),
			('降伏安全率', f"{v['sf_yield']:.3f}", '(OK)' if v['ok_yield'] else '(NG)'),
		])
		
		# 計算式
		section('計算式')
		ensure_space(70)
		c.setFont(font, 8)
		c.drawString(left, y, '・断面積: A = (B×H - b×h) / 100  [cm²]')
		y -= 11
		c.drawString(left, y, '・引張応力: σ = P / A  [kg/cm²]')
		y -= 11
		c.drawString(left, y, '・破断安全率: θb / (安全率 × σ)')
		y -= 11
		c.drawString(left, y, '・降伏安全率: θy / (安全率 × σ)')
		y -= 14
		c.setFont(font, 10)
		
		# 総合判定
		ok_b = v['ok_break']
		ok_y = v['ok_yield']
		c.setFont(font, 10)
		c.drawString(left, y, f"総合判定: {'基準を満たす' if (ok_b and ok_y) else '基準を満たさない'}")
		y -= 18
		
		c.save()


class MainFrame(wx.Frame):
	def __init__(self):
		super().__init__(None,title='車両関連 統合計算ツール',size=wx.Size(960,960))
		nb=wx.Notebook(self)
		nb.AddPage(WeightCalcPanel(nb),'重量計算書')
		#nb.AddPage(CarCalcPanel(nb),'改造審査')
		nb.AddPage(TrailerSpecPanel(nb),'ライト・トレーラの連結仕様検討書')
		nb.AddPage(StabilityAnglePanel(nb),'連結時最大安定角度計算書')
		nb.AddPage(TurningRadiusPanel(nb),'最小回転半径計算書')
		nb.AddPage(AxleStrengthPanel(nb),'車軸強度計算書')
		nb.AddPage(FrameStrengthPanel(nb),'車枠強度計算書')
		nb.AddPage(CouplerStrengthPanel(nb),'連結部強度計算書')
		self.Centre()

def main():
	app=wx.App(); frame=MainFrame(); frame.Show(); app.MainLoop()

if __name__=='__main__':
	main()
