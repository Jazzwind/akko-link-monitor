"""Scrollable Tk content with local wheel routing and no global input hooks."""
import tkinter as tk
from tkinter import ttk


class ScrollPage(ttk.Frame):
    def __init__(self,parent):
        super().__init__(parent)
        self.rowconfigure(0,weight=1);self.columnconfigure(0,weight=1)
        self.viewport=tk.Canvas(self,highlightthickness=0,background='#f4f6fa',
                                yscrollincrement=24,xscrollincrement=24)
        self.vertical=ttk.Scrollbar(self,orient='vertical',command=self.viewport.yview)
        self.viewport.configure(yscrollcommand=self.vertical.set)
        self.viewport.grid(row=0,column=0,sticky='nsew')
        self.vertical.grid(row=0,column=1,sticky='ns')
        self.content=ttk.Frame(self,padding=20)
        self.window=self.viewport.create_window(0,0,window=self.content,anchor='nw')
        self.content.bind('<Configure>',self.resize,add='+')
        self.viewport.bind('<Configure>',self.resize,add='+')
        self.wheel_tag='AkkoScrollPage'+str(id(self))
        self.wheel_remainder={'x':0,'y':0}
        for sequence in ('<MouseWheel>','<Button-4>','<Button-5>'):
            self.bind_class(self.wheel_tag,sequence,self.wheel)

    def resize(self,event=None):
        # Always fit the viewport. Children wrap/reflow instead of widening the
        # entire page; only data tables retain local horizontal scrolling.
        width=max(1,self.viewport.winfo_width())
        height=max(self.viewport.winfo_height(),self.content.winfo_reqheight())
        self.viewport.itemconfigure(self.window,width=width,height=height)
        self.viewport.configure(scrollregion=(0,0,width,height))

    def install_wheel_bindings(self):
        def visit(widget):
            tags=widget.bindtags()
            if self.wheel_tag not in tags:widget.bindtags((self.wheel_tag,*tags))
            for child in widget.winfo_children():visit(child)
        visit(self)

    def wheel(self,event):
        delta=120 if getattr(event,'num',None)==4 else -120 if getattr(event,'num',None)==5 else event.delta
        if not delta:return
        axis='x' if event.state&1 else 'y'
        widget=event.widget
        # Let native table/text bindings consume the wheel while they can move.
        # At their boundary (or when empty), route to the containing page.
        if isinstance(widget,(ttk.Treeview,tk.Text,tk.Listbox)):
            view=getattr(widget,axis+'view')()
            if (delta>0 and view[0]>0.000001) or (delta<0 and view[1]<0.999999):return
        if axis=='x':return
        self.wheel_remainder[axis]+=delta
        steps=int(self.wheel_remainder[axis]/120)
        self.wheel_remainder[axis]-=steps*120
        if steps:getattr(self.viewport,axis+'view_scroll')(-steps*3,'units')
        return 'break'


class FlowFrame(ttk.Frame):
    """Keep related controls together and wrap groups at the available width."""
    def __init__(self,parent):
        super().__init__(parent)
        self.items=[];self.pending=None;self.signature=None
        self.scheduler=self.winfo_toplevel()
        self.bind('<Configure>',self.schedule,add='+')
        self.bind('<Destroy>',self.cleanup,add='+')

    def add(self,widget):
        self.items.append(widget)
        widget.bind('<Configure>',self.schedule,add='+')
        self.schedule()
        return widget

    def schedule(self,event=None):
        if self.pending is None:self.pending=self.scheduler.after_idle(self.reflow)

    def reflow(self):
        self.pending=None
        if not self.winfo_exists():return
        width=max(1,self.winfo_width());x=0;y=0;row_height=0;layout=[]
        for widget in self.items:
            wanted=widget.winfo_reqwidth()+8
            height=widget.winfo_reqheight()
            if x and x+wanted>width:y+=row_height+6;x=0;row_height=0
            layout.append((widget,x,y,wanted-8,height))
            row_height=max(row_height,height);x+=wanted
        signature=tuple((str(widget),x,y,w,h) for widget,x,y,w,h in layout)
        if signature==self.signature:return
        self.signature=signature
        self.configure(height=y+row_height+6)
        for widget,x,y,w,h in layout:widget.place(x=x,y=y,width=w,height=h)

    def cleanup(self,event):
        if event.widget is self and self.pending is not None:
            self.scheduler.after_cancel(self.pending);self.pending=None
