import tkinter as tk
from tkinter import scrolledtext, messagebox, filedialog
from src.engine.webhook_sender import send_markdown, send_image, send_news

class WecomDebugger:
    def __init__(self, root):
        self.root = root
        root.title("企业微信消息调试器")
        root.geometry("650x620")

        # ===== 顶部固定栏：模式 + 发送按钮 =====
        top_frame = tk.Frame(root)
        top_frame.pack(fill="x", padx=10, pady=(10, 5))

        # 模式选择（左）
        self.mode = tk.StringVar(value="md_img")
        tk.Radiobutton(top_frame, text="Markdown + 图片", variable=self.mode, value="md_img",
                       command=self.switch_mode).pack(side="left", padx=5)
        tk.Radiobutton(top_frame, text="新闻图文", variable=self.mode, value="news",
                       command=self.switch_mode).pack(side="left", padx=5)

        # 发送按钮（右）
        tk.Button(top_frame, text="发送到测试群", command=self.send_message,
                  bg="#4CAF50", fg="white", height=1, width=15).pack(side="right", padx=5)

        # ===== 内容区（模式切换容器）=====
        self.container = tk.Frame(root)
        self.container.pack(fill="both", expand=True, padx=10, pady=5)

        self.init_md_img_panel()
        self.init_news_panel()
        self.switch_mode()

    # -------------------- Markdown+图片面板 --------------------
    def init_md_img_panel(self):
        self.panel_md_img = tk.Frame(self.container)

        self.send_md = tk.BooleanVar(value=True)
        self.send_img = tk.BooleanVar(value=False)
        chk = tk.Frame(self.panel_md_img)
        chk.pack(anchor="w")
        tk.Checkbutton(chk, text="Markdown 文本", variable=self.send_md).pack(side="left", padx=5)
        tk.Checkbutton(chk, text="图片", variable=self.send_img).pack(side="left", padx=5)

        tk.Label(self.panel_md_img, text="Markdown 内容:").pack(anchor="w", pady=(10, 0))
        self.text_area = scrolledtext.ScrolledText(self.panel_md_img, height=10)
        self.text_area.pack(fill="both", expand=True, pady=5)

        btn_frame = tk.Frame(self.panel_md_img)
        btn_frame.pack(pady=5)
        tk.Button(btn_frame, text="加粗", command=self.insert_bold).pack(side="left", padx=2)
        tk.Button(btn_frame, text="标题", command=self.insert_heading).pack(side="left", padx=2)
        tk.Button(btn_frame, text="引用块", command=self.insert_quote).pack(side="left", padx=2)
        tk.Button(btn_frame, text="无序列表", command=self.insert_list).pack(side="left", padx=2)
        tk.Button(btn_frame, text="链接", command=self.insert_link).pack(side="left", padx=2)

        self.image_path = tk.StringVar()
        self.image_label = tk.Label(self.panel_md_img, text="未选择图片", fg="gray")
        self.image_label.pack(anchor="w", pady=(10, 0))
        tk.Button(self.panel_md_img, text="选择图片文件", command=self.select_image).pack(anchor="w", pady=(2, 0))

    # -------------------- 新闻图文面板 --------------------
    def init_news_panel(self):
        self.panel_news = tk.Frame(self.container)

        toolbar = tk.Frame(self.panel_news)
        toolbar.pack(fill="x", pady=(0, 5))
        tk.Button(toolbar, text="➕ 添加一条图文", command=self.add_article).pack(side="left", padx=5)
        tk.Button(toolbar, text="➖ 删除最后一条", command=self.remove_article).pack(side="left", padx=5)
        tk.Label(toolbar, text="（最多 8 条）", fg="gray").pack(side="left", padx=5)

        # 滚动区域
        canvas_frame = tk.Frame(self.panel_news)
        canvas_frame.pack(fill="both", expand=True)
        self.news_canvas = tk.Canvas(canvas_frame, borderwidth=0, highlightthickness=0)
        scrollbar = tk.Scrollbar(canvas_frame, orient="vertical", command=self.news_canvas.yview)
        self.scrollable_frame = tk.Frame(self.news_canvas)
        self.scrollable_frame.bind("<Configure>", lambda e: self.news_canvas.configure(
            scrollregion=self.news_canvas.bbox("all")))
        self.news_canvas.create_window((0, 0), window=self.scrollable_frame, anchor="nw")
        self.news_canvas.configure(yscrollcommand=scrollbar.set)
        self.news_canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        self.article_widgets = []
        # 默认添加一条空图文
        self.add_article()

    # -------------------- 模式切换 --------------------
    def switch_mode(self):
        self.panel_md_img.pack_forget()
        self.panel_news.pack_forget()
        if self.mode.get() == "md_img":
            self.panel_md_img.pack(fill="both", expand=True)
        else:
            self.panel_news.pack(fill="both", expand=True)

    # -------------------- 新闻条目操作 --------------------
    def add_article(self):
        if len(self.article_widgets) >= 8:
            messagebox.showwarning("限制", "最多支持 8 条图文")
            return

        frame = tk.LabelFrame(self.scrollable_frame, text=f"图文 {len(self.article_widgets)+1}", padx=5, pady=5)
        frame.pack(fill="x", pady=2)

        tk.Label(frame, text="标题 *").grid(row=0, column=0, sticky="e")
        title_var = tk.StringVar()
        tk.Entry(frame, textvariable=title_var, width=45).grid(row=0, column=1, padx=5, pady=2)

        tk.Label(frame, text="描述").grid(row=1, column=0, sticky="e")
        desc_var = tk.StringVar()
        tk.Entry(frame, textvariable=desc_var, width=45).grid(row=1, column=1, padx=5, pady=2)

        tk.Label(frame, text="链接 *").grid(row=2, column=0, sticky="e")
        url_var = tk.StringVar()
        tk.Entry(frame, textvariable=url_var, width=45).grid(row=2, column=1, padx=5, pady=2)

        tk.Label(frame, text="缩略图 URL").grid(row=3, column=0, sticky="e")
        picurl_var = tk.StringVar()
        tk.Entry(frame, textvariable=picurl_var, width=45).grid(row=3, column=1, padx=5, pady=2)

        self.article_widgets.append({
            "frame": frame,
            "title": title_var,
            "desc": desc_var,
            "url": url_var,
            "picurl": picurl_var
        })

    def remove_article(self):
        if self.article_widgets:
            last = self.article_widgets.pop()
            last["frame"].destroy()

    # -------------------- 发送逻辑 --------------------
    def send_message(self):
        mode = self.mode.get()
        if mode == "md_img":
            self.send_md_img()
        else:
            self.send_news_msg()

    def send_md_img(self):
        md_on = self.send_md.get()
        img_on = self.send_img.get()
        if not md_on and not img_on:
            messagebox.showwarning("提示", "至少选择一种消息类型")
            return
        if md_on:
            content = self.text_area.get("1.0", tk.END).strip()
            if not content:
                messagebox.showwarning("警告", "Markdown 内容不能为空")
                return
            success, resp = send_markdown(content)
            if not success:
                messagebox.showerror("Markdown 失败", resp.get("errmsg", str(resp)))
                return
        if img_on:
            path = self.image_path.get()
            if not path:
                messagebox.showwarning("警告", "请先选择图片")
                return
            success, resp = send_image(path)
            if not success:
                messagebox.showerror("图片失败", resp.get("errmsg", str(resp)))
                return
        messagebox.showinfo("成功", "消息已发送")

    def send_news_msg(self):
        articles = []
        for w in self.article_widgets:
            title = w["title"].get().strip()
            url = w["url"].get().strip()
            if not title or not url:
                messagebox.showwarning("校验", f"图文 {len(articles)+1} 的标题和链接为必填项")
                return
            art = {"title": title, "url": url}
            desc = w["desc"].get().strip()
            if desc:
                art["description"] = desc
            picurl = w["picurl"].get().strip()
            if picurl:
                art["picurl"] = picurl
            articles.append(art)

        if not articles:
            messagebox.showwarning("提示", "请至少添加一条图文")
            return

        success, resp = send_news(articles)
        if success:
            messagebox.showinfo("成功", f"{len(articles)} 条图文已发送")
        else:
            messagebox.showerror("失败", resp.get("errmsg", str(resp)))

    # ---------- Markdown 格式按钮 ----------
    def insert_bold(self): self._wrap_selection("**")
    def insert_heading(self): self._wrap_selection("## ")
    def insert_quote(self): self._wrap_selection("> ", line_prefix=True)
    def insert_list(self): self._wrap_selection("- ", line_prefix=True)
    def insert_link(self):
        try:
            selected = self.text_area.get(tk.SEL_FIRST, tk.SEL_LAST)
        except tk.TclError:
            selected = "链接描述"
        self.text_area.insert(tk.INSERT, f"[{selected}](https://example.com)")

    def _wrap_selection(self, wrapper, line_prefix=False):
        try:
            if line_prefix:
                start = self.text_area.index(tk.SEL_FIRST)
                end = self.text_area.index(tk.SEL_LAST)
                selected = self.text_area.get(start, end)
                lines = selected.split("\n")
                new_text = "\n".join(wrapper + line for line in lines)
                self.text_area.delete(start, end)
                self.text_area.insert(start, new_text)
            else:
                start = self.text_area.index(tk.SEL_FIRST)
                end = self.text_area.index(tk.SEL_LAST)
                selected = self.text_area.get(start, end)
                self.text_area.delete(start, end)
                self.text_area.insert(start, wrapper + selected + wrapper)
        except tk.TclError:
            messagebox.showinfo("提示", "请先选中要修改的文本")

    def select_image(self):
        path = filedialog.askopenfilename(
            title="选择图片",
            filetypes=[("图片", "*.png *.jpg *.jpeg *.gif *.bmp"), ("所有文件", "*.*")]
        )
        if path:
            self.image_path.set(path)
            self.image_label.config(text=path, fg="black")

if __name__ == "__main__":
    root = tk.Tk()
    app = WecomDebugger(root)
    root.mainloop()
