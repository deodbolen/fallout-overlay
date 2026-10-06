"""Apply and verify an empty X11 input region, independently of GTK mapping."""
import ctypes
from ctypes import c_void_p,c_ulong,c_int,c_char_p,POINTER,byref


def make_click_through(xid):
    x11=ctypes.CDLL('libX11.so.6'); shape=ctypes.CDLL('libXext.so.6')
    x11.XOpenDisplay.argtypes=[c_char_p]; x11.XOpenDisplay.restype=c_void_p
    x11.XCloseDisplay.argtypes=[c_void_p]
    x11.XSync.argtypes=[c_void_p,c_int]
    x11.XFree.argtypes=[c_void_p]
    shape.XShapeQueryExtension.argtypes=[c_void_p,POINTER(c_int),POINTER(c_int)]
    shape.XShapeCombineRectangles.argtypes=[c_void_p,c_ulong,c_int,c_int,c_int,c_void_p,c_int,c_int,c_int]
    shape.XShapeGetRectangles.argtypes=[c_void_p,c_ulong,c_int,POINTER(c_int),POINTER(c_int)]
    shape.XShapeGetRectangles.restype=c_void_p
    display=x11.XOpenDisplay(None)
    if not display: raise RuntimeError('Could not open the X11 display.')
    try:
        event,error=c_int(),c_int()
        if not shape.XShapeQueryExtension(display,byref(event),byref(error)):
            raise RuntimeError('X11 SHAPE extension is unavailable.')
        # ShapeInput=2, ShapeSet=0; zero rectangles makes every pixel click-through.
        shape.XShapeCombineRectangles(display,xid,2,0,0,None,0,0,0)
        x11.XSync(display,0)
        count,order=c_int(),c_int()
        rectangles=shape.XShapeGetRectangles(display,xid,2,byref(count),byref(order))
        if rectangles: x11.XFree(rectangles)
        if count.value!=0: raise RuntimeError('Overlay input region is not empty.')
        return True
    finally: x11.XCloseDisplay(display)
