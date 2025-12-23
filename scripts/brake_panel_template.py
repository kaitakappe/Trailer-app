
# BrakeStrengthPanel insert code (to paste before TowingSpecPanel)

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
		
		# スクロール & グリッド
		scroll = wx.ScrolledWindow(self, style=wx.VSCROLL)
		scroll.SetScrollRate(0, 20)
		scroll_sizer = wx.BoxSizer(wx.VERTICAL)
		
		# 寸法セクション
		self._add_section(scroll_sizer, "寸法 (mm)", scroll)
		self.r_inner = self._add(scroll_sizer, '内径', '210', scroll)
		self.r_outer = self._add(scroll_sizer, '外径', '230', scroll)
		self.width = self._add(scroll_sizer, '幅', '50', scroll)
		
		# 圧力セクション
		self._add_section(scroll_sizer, "圧力 (MPa)", scroll)
		self.pressure = self._add(scroll_sizer, '内圧', '25', scroll)
		
		# 材料セクション
		self._add_section(scroll_sizer, "材料強度 (N/mm²)", scroll)
		self.tensile = self._add(scroll_sizer, '引張強さ', '1000', scroll)
		self.yield_pt = self._add(scroll_sizer, '降伏点', '850', scroll)
		self.shear = self._add(scroll_sizer, 'せん断強さ', '600', scroll)
		
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
			
			text = format_brake_strength_result(self.last)
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
			
			self.export_to_path(output_path)
			wx.MessageBox(f'PDFを保存しました:\n{output_path}', '完了', wx.ICON_INFORMATION)
		except Exception as e:
			wx.MessageBox(f'PDF出力エラー: {e}', 'エラー', wx.ICON_ERROR)
	
	def export_to_path(self, path):
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
		
		# タイトル
		c.setFont(font, 16)
		c.drawCentredString(w/2, h - 50, '制動装置（ブレーキドラム）強度計算書')
		
		y = h - 100
		c.setFont(font, 11)
		
		# 寸法
		items = [
			('寸法・圧力', ''),
			(f"  内径: {self.last['r_inner']:.1f} mm", ''),
			(f"  外径: {self.last['r_outer']:.1f} mm", ''),
			(f"  幅: {self.last['width']:.1f} mm", ''),
			(f"  内圧: {self.last['pressure_mpa']:.3f} MPa", ''),
			(f"  径比 k = {self.last['k_diameter_ratio']:.3f}", ''),
			('', ''),
			('応力計算結果', ''),
			(f"  Hoop応力（内面）: {self.last['sigma_hoop_inner']:.2f} N/mm²", ''),
			(f"  等価応力: {self.last['equivalent_stress']:.2f} N/mm²", ''),
			('', ''),
			('材料強度', ''),
			(f"  引張強さ: {self.last['material_tensile_strength']:.1f} N/mm²", ''),
			(f"  降伏点: {self.last['material_yield_strength']:.1f} N/mm²", ''),
			(f"  せん断強さ: {self.last['material_shear_strength']:.1f} N/mm²", ''),
			('', ''),
			('安全率', ''),
			(f"  引張: {self.last['safety_factor_tensile']:.2f} {'◎' if self.last['ok_tensile'] else '✕'}", ''),
			(f"  降伏: {self.last['safety_factor_yield']:.2f} {'◎' if self.last['ok_yield'] else '✕'}", ''),
			(f"  せん断: {self.last['safety_factor_shear']:.2f} {'◎' if self.last['ok_shear'] else '✕'}", ''),
			('', ''),
			(f"総合判定: {'適合' if self.last['ok_overall'] else '不適合'}", ''),
		]
		
		for label, _ in items:
			if label == '':
				y -= 10
			elif label.startswith('  '):
				c.drawString(70, y, label)
				y -= 18
			else:
				c.setFont(font, 12)
				c.drawString(50, y, label)
				c.setFont(font, 11)
				y -= 20
			
			if y < 80:
				c.showPage()
				c.setFont(font, 11)
				y = h - 60
		
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
		self.export_to_path(path)

