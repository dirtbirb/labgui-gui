import threading
import wx
from queue import Queue

try:
    import numpy as np
except ImportError:
    pass

try:
    import cv2
except ImportError:
    pass

# Constants for GUI construction
pad = 25
pad_inner = 3
pad_outer = 10
sz_img = (1280, 800)
sz_thumb = (128, 80)
sz_btn = (2*pad, 2*pad)
sz1 = (2*pad, pad)
wd1 = (2*pad, -1)
ht1 = (-1, pad)
sz2 = (3*pad, pad)
sz3 = (4*pad, pad)
span1 = wx.GBSpan(1, 1)
span2 = wx.GBSpan(1, 2)
span3 = wx.GBSpan(1, 3)
ALIGN_CENTER_RIGHT = wx.ALIGN_RIGHT + wx.ALIGN_CENTER_VERTICAL
bg_img = wx.Colour(0, 0, 0).MakeDisabled()


def debug(msg):
    # TODO: make actual debug function
    print(msg)


def validate(v, mn=0, mx=255):
    return max(min(v, mx), mn)


def to_float(value):
    ''' Try to convert string to float; return string if failed '''
    try:
        value = float(value)
    except ValueError:
        pass
    return value


def average_top_px(img, n=3):
    ''' Return average of top n pixels from an image '''
    if n == 1:
        ret = img.max()
    else:
        ret = np.partition(img.flatten(), -n)[-n:].mean()
    return ret


def get_top_px(img, n=1):
    ''' Return top nth pixel from an image '''
    if n == 1:
        ret = img.max()
    else:
        ret = np.partition(img.flatten(), -n)[-n]
    return ret


def is_color(img):
    ''' Return True if image contains a color channel, False otherwise '''
    return len(img.shape) == 3


# wx.Dialog -------------------------------------------------------------------

# def showModalDialog(title, message, style):
#     dialog = wx.MessageDialog(self, message, title, style)
#     result = dialog:ShowModal()
#     dialog.Destroy()
#     return result
#
#
# def showInputDialog(title, message, default, style):
#     dialog = wx.TextEntryDialog(self, message, title, default, style)
#     dialog.ShowModal()
#     result = dialog:GetValue()
#     dialog.Destroy()
#     return result
#
#
# def ErrorDialog(message):
#     showModalDialog("ERROR", message, wx.OK + wx.ICON_ERROR)
#     return False
#
#
# def InfoDialog(message):
#     return showModalDialog("", message, wx.OK)
#
#
# def InputDialog(title, message, default):
#     default = default or ""
#     return showInputDialog(title, message, default, wx.OK + wx.CANCEL)


def FileDialog(msg, ext=None, save=False):
    ''' Show file save/open dialog with optional extension filter '''
    if save:
        style = wx.FD_SAVE
    else:
        style = wx.FD_OPEN
    dlg = wx.FileDialog(None, msg, wildcard='*'+ext, style=style)
    if dlg.ShowModal() == wx.ID_OK:
        fn = dlg.GetPath()
        if ext and not fn[-4:] in (ext, ext.lower(), ext.upper()):
            fn += ext
    else:
        fn = False
    return fn


# Misc ------------------------------------------------------------------------

class GuiImage(wx.Window):
    ''' Basic wx Window for painting images on '''

    def __init__(self, *args, **kwargs):
        # Default size
        if 'size' not in kwargs:
            kwargs['size'] = sz_img
        super().__init__(*args, **kwargs)
        # Default background color
        self.SetBackgroundColour(bg_img)

    # def display(window, img, img_done_flag, dc_processes=[]):
    #     ''' Thread-safe method for wx portion of image display '''
    #     # Skip frame if resized incorrectly for current window
    #     dc, sz = wx.ClientDC(window), window.GetSize()
    #     if sz == (img.shape[1], img.shape[0]):
    #         # Draw image
    #         dc.DrawBitmap(wx.Bitmap.FromBuffer(*sz, img), 0, 0)
    #         for process in dc_processes:
    #             process(dc)
    #         # Show on GUI
    #         window.Update()
    #     img_done_flag.set()


class GuiSizer(wx.GridBagSizer):
    ''' wx GridBagSizer with default padding '''

    def __init__(self, *items, hpad=None, vpad=None):
        super().__init__(hpad or pad_inner, vpad or pad_inner)
        for item in items:
            self.Add(*item)

    def AddList(sizer, *items):
        for item in items:
            sizer.Add(*item)


# wx.Panel --------------------------------------------------------------------

class GuiPanel(wx.Panel):
    ''' Panel containing GUI elements that can be read/set like attributes '''

    def __getattribute__(self, name):
        ''' Retrieve value of GUI elements as properties '''
        # If attribute "name" is a wx object...
        elem = object.__getattribute__(self, name)
        if isinstance(elem, wx.Object):
            # Return floats from numerical values, strings otherwise
            if isinstance(elem, (wx.TextCtrl, wx.ToggleButton)):
                return to_float(elem.GetValue())
            # Return numerical index from Choice, ComboBox, RadioBox
            # HACK: Can't retrieve string selection!
            elif isinstance(elem, wx.ItemContainerImmutable):
                return elem.GetSelection()
            # Return text value of StaticText
            elif isinstance(elem, wx.StaticText):
                return to_float(elem.GetLabel())
        # Return anything else as normal
        return elem

    def __setattr__(self, name, value):
        ''' Set value of GUI elements as properties '''
        # If attribute "name" already exists...
        if hasattr(self, name):
            # If attribute "name" is a wx object...
            elem = object.__getattribute__(self, name)
            if isinstance(elem, wx.Object):
                # "value" is new state of ToggleButton
                if isinstance(elem, wx.ToggleButton):
                    elem.SetValue(value)
                    return
                # "value" is new string to display for TextCtrl
                elif isinstance(elem, wx.TextCtrl):
                    elem.SetValue(str(value))
                    return
                # "value" is new selection for Choice, ComboBox, RadioBox
                elif isinstance(elem, wx.ItemContainerImmutable):
                    if isinstance(value, int):
                        elem.SetSelection(value)
                    else:
                        elem.SetStringSelection(str(value))
                    return
                # "value" is new string to display for StaticText
                elif isinstance(elem, wx.StaticText):
                    elem.SetLabel(str(value))
                    return
        # Set anything else as normal
        object.__setattr__(self, name, value)

    def MakeSizerAndFit(self, *items):
        ''' Similar to SetSizerAndFit, but creates a GuiSizer first '''
        self.SetSizerAndFit(GuiSizer(*items))


class ViewPanel(GuiPanel):
    ''' View options
        Unlike other panels, this panel is tightly integrated with BasicGui.
        Many functions use GetParent() to manipulate BasicGui directly. '''

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.inserted_panels = []
        self.video_writer = None

        lbl = wx.StaticText(self, label='View')
        source = wx.Choice(self)
        play_btn = wx.ToggleButton(self, label='Play', size=sz1)
        full_btn = wx.Button(self, label='Full', size=sz1)
        save_lbl = wx.StaticText(self, label='Save')
        save_img_btn = wx.Button(self, label='Image', size=sz1)
        save_vid_btn = wx.ToggleButton(self, label='Video', size=sz1)

        save_img_btn.Bind(wx.EVT_BUTTON, self.save_img)
        save_vid_btn.Bind(wx.EVT_TOGGLEBUTTON, self.save_vid)
        source.Bind(wx.EVT_CHOICE, self.select_source)

        self.MakeSizerAndFit(
            (lbl, wx.GBPosition(0, 0), span2),
            (source, wx.GBPosition(1, 0), span3, wx.EXPAND),
            (play_btn, wx.GBPosition(2, 1), span1, wx.EXPAND),
            (full_btn, wx.GBPosition(2, 2), span1, wx.EXPAND),
            (save_lbl, wx.GBPosition(3, 0), span1, ALIGN_CENTER_RIGHT),
            (save_img_btn, wx.GBPosition(3, 1), span1, wx.EXPAND),
            (save_vid_btn, wx.GBPosition(3, 2), span1, wx.EXPAND))

        self.source = source
        self.save_img_btn = save_img_btn
        self.save_vid_btn = save_vid_btn
        self.fullscreen = full_btn

    def save_img(self, event=None):
        ''' Save still image via dialog '''
        parent = self.GetParent()
        if parent and hasattr(parent, 'image') and parent.image is not None:
            img = parent.image.copy()
            fn = FileDialog('Save image', '.png', save=True)
            if fn:
                cv2.imwrite(fn, img, (cv2.IMWRITE_PNG_COMPRESSION, 5))

    def save_vid(self, event=None):
        ''' Start/stop recording, with save dialog '''
        parent = self.GetParent()
        if parent and hasattr(parent, 'image') and parent.image is not None:
            if self.save_vid_btn:   # Start recording (via dialog)
                fn = FileDialog('Save video', '.avi', save=True)
                if fn:
                    codec = cv2.VideoWriter_fourcc('M', 'J', 'P', 'G')
                    fps = 10
                    shape = self.GetParent().image.shape[:2]
                    self.video_writer = cv2.VideoWriter(fn, codec, fps, shape)
                else:               # Cancel recording
                    self.save_vid_btn = False
            else:                   # Finish recording
                if self.video_writer:
                    self.video_writer.release()
                self.video_writer = None
        else:
            self.save_vid_btn = False

    def add_source(self, name, obj, panels):
        self.sources.Append(name, (obj, panels))

    def add_sources(self, sources):
        if isinstance(sources, list):   # Add each from the list
            for s in sources:
                self.add_source(s)
        else:
            self.add_source(sources)    # If not actually a list

    def del_source(self, index):
        self.sources.Delete(index)

    def select_source(self, event=None):
        parent = self.GetParent()
        layout = parent.layout
        index = self.source
        obj, new_panels = self.source[index].GetClientData()
        # Create source object
        try:
            parent.cam = obj(parent.img_queue)
        except Exception as e:
            print("Error: couldn't create sensor object. Details:\n", e)
            self.del_source(index)
            new_panels = []
        # Remove old panels
        for old_panel in self.inserted_panels:
            panel, location = old_panel
            for i, gui_panel in enumerate(layout[location]):
                if type(panel) == type(gui_panel):
                    layout[location].pop(i)
        # Add new panels and reassemble GUI
        self.inserted_panels = new_panels
        for new_panel in new_panels:
            panel, location = new_panel
            parent.layout[location].insert(panel, 1)
        parent.Assemble()


# Sensor controls

class ConnectPanel(GuiPanel):
    ''' Sensor control and basic info '''

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        lbl = wx.StaticText(self, label='Sensor')
        sensor_ip_lbl = wx.StaticText(self, label='IP')
        sensor_ip = wx.TextCtrl(self, size=sz2, style=wx.TE_PROCESS_ENTER)
        sensor_id_lbl = wx.StaticText(self, label='ID')
        sensor_id = wx.TextCtrl(
            self, size=sz2, value='0', style=wx.TE_PROCESS_ENTER)

        self.MakeSizerAndFit(
            (lbl, wx.GBPosition(0, 0), span2),
            (sensor_ip_lbl, wx.GBPosition(1, 0), span1, ALIGN_CENTER_RIGHT),
            (sensor_ip, wx.GBPosition(1, 1), span1, wx.EXPAND),
            (sensor_id_lbl, wx.GBPosition(2, 0), span1, ALIGN_CENTER_RIGHT),
            (sensor_id, wx.GBPosition(2, 1), span1))

        self.sensor_ip = sensor_ip
        self.sensor_id = sensor_id

        # TODO: Add sensor info


class RoiPanel(GuiPanel):
    ''' ROI (Region Of Interest) control '''

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        apply = wx.Button(self, label='Set', size=sz1)
        load = wx.Button(self, label='Load', size=sz1)
        lbl = wx.StaticText(self, label='ROI')
        y_lbl = wx.StaticText(self, label='y')
        x_lbl = wx.StaticText(self, label='x')
        offset_lbl = wx.StaticText(self, label='Offset')
        size_lbl = wx.StaticText(self, label='Size')
        x = wx.TextCtrl(self, value='0.0', size=sz1, style=wx.TE_PROCESS_ENTER)
        w = wx.TextCtrl(self, value='1.0', size=sz1, style=wx.TE_PROCESS_ENTER)
        y = wx.TextCtrl(self, value='0.0', size=sz1, style=wx.TE_PROCESS_ENTER)
        h = wx.TextCtrl(self, value='1.0', size=sz1, style=wx.TE_PROCESS_ENTER)

        self.MakeSizerAndFit(
            (lbl, wx.GBPosition(0, 0), span3),
            (offset_lbl, wx.GBPosition(1, 1), span1,
                wx.ALIGN_CENTER_HORIZONTAL),
            (size_lbl, wx.GBPosition(1, 2), span1, wx.ALIGN_CENTER_HORIZONTAL),
            (x_lbl, wx.GBPosition(2, 0), span1, ALIGN_CENTER_RIGHT),
            (x, wx.GBPosition(2, 1), span1),
            (w, wx.GBPosition(2, 2), span1),
            (y_lbl, wx.GBPosition(3, 0), span1, ALIGN_CENTER_RIGHT),
            (y, wx.GBPosition(3, 1), span1),
            (h, wx.GBPosition(3, 2), span1),
            (apply, wx.GBPosition(4, 1), span1),
            (load, wx.GBPosition(4, 2), span1))

        self.apply = apply
        self.load = load
        self.x = x
        self.w = w
        self.y = y
        self.h = h


class MetricsPanel(GuiPanel):
    ''' Metrics readout panel
        Update values (not display!) by editing dict 'values'
        Update display with most recent values with update()
        Update list of values to be displayed with build()
        Start regular updates by passing an Event flag to start()
        Stop regular updates with stop() '''

    def __init__(self, *args, **kwargs):
        if 'values' in kwargs:
            self.values = kwargs.pop('values')
        else:
            self.values = {}
        super().__init__(*args, **kwargs)
        self.build()
        self.updating = False

    def build(self):
        self.display = {}
        new_items = [(
            wx.StaticText(self, label='Metrics'), wx.GBPosition(0, 0), span2)]
        for name in self.values:
            # Replace 'None' with '-' just to keep it clean
            v = self.values[name]
            if v is None:
                v = '-'
            else:
                v = str(v)
            # Build display
            i = len(new_items)
            label = wx.StaticText(self, label=name + ': ')
            value = wx.StaticText(self, label=v)
            new_items.append(
                (label, wx.GBPosition(i, 0), span1, ALIGN_CENTER_RIGHT))
            new_items.append(
                (value, wx.GBPosition(i, 1)))
            self.display[name] = value
        self.MakeSizerAndFit(*new_items)

    def update(self):
        for name in self.values:
            if name in self.display:
                self.display[name].SetValue(str(self.values[name]))

    def start(self, update_flag):
        def __update_loop(self):
            while True:
                update_flag.wait()
                self.update()
                update_flag.clear()

        self.updating = threading.Thread(
            target=self.__update_loop, args=(update_flag, ))
        self.updating.daemon = True
        self.updating.start()

    def stop(self):
        if self.updating:
            self.updating.terminate()
        self.updating = False


# Image processing

class ColorPanel(GuiPanel):
    ''' Color processing '''

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        colormaps = (
            'force gray',
            'no mapping',
            'autumn',
            'bone',
            'cool',
            'hot',
            'HSV',
            'jet',
            'ocean',
            'pink',
            'rainbow',
            'sping',
            'summer',
            'winter')
        label = wx.StaticText(self, label='Color')
        colormap = wx.Choice(self, choices=colormaps)
        colormap.SetSelection(1)     # no colormap
        range_btn = wx.ToggleButton(self, label='Range', size=sz2)
        range_val = wx.TextCtrl(
            self, value='255', size=sz1, style=wx.TE_PROCESS_ENTER)
        gamma_btn = wx.ToggleButton(self, label='Gamma', size=sz2)
        gamma_val = wx.TextCtrl(
            self, value='2.2', size=sz1, style=wx.TE_PROCESS_ENTER)
        sat_btn = wx.ToggleButton(self, label='Highlight', size=sz2)
        sat_val = wx.TextCtrl(
            self, value='255', size=sz1, style=wx.TE_PROCESS_ENTER)

        range_btn.Bind(wx.EVT_TOGGLEBUTTON, self.set_range)
        range_val.Bind(wx.EVT_TEXT_ENTER, self.set_range)
        gamma_btn.Bind(wx.EVT_TOGGLEBUTTON, self.set_gamma)
        gamma_val.Bind(wx.EVT_TEXT_ENTER, self.set_gamma)
        sat_btn.Bind(wx.EVT_TOGGLEBUTTON, self.set_sat)
        sat_val.Bind(wx.EVT_TEXT_ENTER, self.set_sat)

        self.MakeSizerAndFit(
            (label, wx.GBPosition(0, 0), span2),
            (colormap, wx.GBPosition(1, 0), span2, wx.EXPAND),
            (range_btn, wx.GBPosition(2, 0), span1, wx.EXPAND),
            (range_val, wx.GBPosition(2, 1), span1, wx.EXPAND),
            (gamma_btn, wx.GBPosition(3, 0), span1, wx.EXPAND),
            (gamma_val, wx.GBPosition(3, 1), span1, wx.EXPAND),
            (sat_btn, wx.GBPosition(4, 0), span1, wx.EXPAND),
            (sat_val, wx.GBPosition(4, 1), span1, wx.EXPAND))

        self.colormap = colormap
        self.range_btn = range_btn
        self.range_val = range_val
        self.gamma_btn = gamma_btn
        self.gamma_val = gamma_val
        self.sat_btn = sat_btn
        self.sat_val = sat_val

        self.set_gamma()

    def set_range(self, event=None):
        ''' Validate dynamic range value '''
        if self.range_btn:
            try:
                v = validate(int(self.range_val))
            except ValueError:
                v = 255
            self.range_val = v

    def set_gamma(self, event=None):
        ''' Validate gamma value and create look-up table (LUT) '''
        if self.gamma_btn:
            try:
                # Validate
                gamma = validate(self.gamma_val, 0.0, 10.0)
                # Create look-up table (LUT)
                self.gamma_lut = np.array(
                    np.arange(0, 1, 1/256) ** (1/gamma) * 255 + 0.5, np.uint8)
            except ValueError:
                gamma = 2.2
            # Update GUI
            self.gamma_val = gamma

    def set_sat(self, event=None):
        ''' Validate dynamic range value '''
        if self.sat_btn:
            try:
                v = validate(int(self.sat_val))
            except ValueError:
                v = 255
            self.sat_val = v

    def colormap_img(self, img):
        ''' Apply selected colormap by index '''
        colormap = self.colormap - 2
        if colormap > -1:                               # Colormap
            img = cv2.applyColorMap(img, colormap)
        elif colormap == -2 and is_color(img):    # Force gray
            img = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        return img

    def range_img(self, img):
        ''' Stretch dynamic range to be from 0 to self.range_val '''
        if self.range_btn:
            img -= img.min()
            f = self.range_val / get_top_px(img, 20)
            img = np.uint8(np.where(img < 255 / f, img * f, 255))
        return img

    def gamma_img(self, img):
        ''' Apply gamma curve using lookup table '''
        if self.gamma_btn:
            img = cv2.LUT(img, self.gamma_lut)
        return img

    def find_sat_img(self, img):
        ''' Find and save locations of pixels above given threshold '''
        if self.sat_btn:
            if is_color(img):
                self.saturated = np.logical_or.reduce(img >= self.sat_val, 2)
            else:
                self.saturated = img >= self.sat_val
        return img

    def apply_sat_img(self, img):
        ''' Make previously-saved pixels red '''
        if self.sat_btn and hasattr(self, 'saturated'):
            if not is_color(img):
                img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
            img[self.saturated] = (0, 0, 255)   # red
        return img

    def process_img(self, img):
        ''' Run all image processes from this panel in order '''
        processes = (
            self.find_sat_img,
            self.range_img,
            self.gamma_img,
            self.colormap_img,
            self.apply_sat_img)
        for process in processes:
            img = process(img)
        return img


class FlatFieldPanel(GuiPanel):
    ''' Flat field controls '''

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.ff = None  # Flat frame

        lbl = wx.StaticText(self, label='Flat field')
        thumb = GuiImage(self, size=sz_thumb)
        save = wx.Button(self, label='Update', size=sz2)
        apply = wx.ToggleButton(self, label='Apply', size=sz2)

        save.Bind(wx.EVT_BUTTON, self.save)
        apply.Bind(wx.EVT_TOGGLEBUTTON, self.validate)

        self.MakeSizerAndFit(
            (lbl, wx.GBPosition(0, 0), span2),
            (thumb, wx.GBPosition(1, 0), span2, wx.ALIGN_CENTER),
            (save, wx.GBPosition(2, 0), span1),
            (apply, wx.GBPosition(2, 1), span1))

        self.save = save
        self.apply = apply
        self.thumb = thumb

    def save(self, event=None):
        ''' Update flat field and thumbnail '''
        # Save camera image
        self.ff = self.GetParent().cam.img.copy()

        # Update thumbnail on gui
        thumb = cv2.resize(self.ff, sz_thumb)
        if is_color(thumb):
            thumb = cv2.cvtColor(thumb, cv2.COLOR_BGR2RGB)
        else:
            thumb = cv2.cvtColor(thumb, cv2.COLOR_GRAY2RGB)
        dc = wx.ClientDC(self.thumb)
        dc.DrawBitmap(wx.Bitmap.FromBuffer(*sz_thumb, thumb), 0, 0)
        self.thumb.Update()

    def validate(self, event=None):
        if self.ff is None:
            self.apply = False

    def flatfield_img(self, img):
        if self.apply:
            # Cancel if image size or color depth has changed
            if self.ff.shape != img.shape:
                self.apply = False
            else:
                img = np.where(img > self.ff, img - self.ff, 0)
        return img

    def process_img(self, img):
        return self.flatfield_img(img)


class TargetPanel(GuiPanel):
    ''' Target overlay '''

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.img_size = sz_img  # Updated in process_img / process_dc

        # These can't be initialized at the class level...
        self.target_pen = wx.Pen((0, 200, 0), 2)  # Lime green
        self.target_brush = wx.Brush((0, 0, 0), wx.BRUSHSTYLE_TRANSPARENT)

        label = wx.StaticText(self, label='Target')
        self.targets = ('no target', 'crosshair', 'box', 'circle')
        target = wx.Choice(self, choices=self.targets)
        size_lbl = wx.StaticText(self, label='Size ')
        size = wx.TextCtrl(self, size=sz1, style=wx.TE_PROCESS_ENTER)
        reset_btn = wx.Button(
            self, label='Reset', size=sz1, style=wx.BU_EXACTFIT)
        orig_lbl = wx.StaticText(self, label='Origin ')
        x = wx.TextCtrl(self, size=sz1, style=wx.TE_PROCESS_ENTER)
        y = wx.TextCtrl(self, size=sz1, style=wx.TE_PROCESS_ENTER)
        px_lbl = wx.StaticText(self, label='x, y ')
        px_x = wx.StaticText(self, size=wd1, style=wx.ALIGN_RIGHT)
        px_y = wx.StaticText(self, size=wd1, style=wx.ALIGN_RIGHT)

        reset_btn.Bind(wx.EVT_BUTTON, self.reset)
        for elem in (x, y, size):
            elem.Bind(wx.EVT_TEXT_ENTER, self.set_size)

        self.MakeSizerAndFit(
            (label, wx.GBPosition(0, 0), span3, wx.EXPAND),
            (target, wx.GBPosition(1, 0), span3, wx.EXPAND),
            (size_lbl, wx.GBPosition(2, 0), span1, ALIGN_CENTER_RIGHT),
            (size, wx.GBPosition(2, 1), span1, wx.EXPAND),
            (reset_btn, wx.GBPosition(2, 2), span1, wx.EXPAND),
            (orig_lbl, wx.GBPosition(3, 0), span1, ALIGN_CENTER_RIGHT),
            (x, wx.GBPosition(3, 1), span1, wx.EXPAND),
            (y, wx.GBPosition(3, 2), span1, wx.EXPAND),
            (px_lbl, wx.GBPosition(4, 0), span1, ALIGN_CENTER_RIGHT),
            (px_x, wx.GBPosition(4, 1), span1, ALIGN_CENTER_RIGHT | wx.EXPAND),
            (px_y, wx.GBPosition(4, 2), span1, ALIGN_CENTER_RIGHT | wx.EXPAND))

        self.target = target
        self.size = size
        self.x = x
        self.y = y
        self.px_x = px_x
        self.px_y = px_y
        self.reset_btn = reset_btn

        self.reset()

    def reset(self, event=None):
        self.target = 0
        self.x = '0.5'
        self.y = '0.5'
        self.size = '20'
        self.set_size()

    def set_size(self, event=None):
        # TODO: Save/update config

        # Validate input
        for v in (self.x, self.y, self.size):
            if isinstance(v, str):
                self.reset()
                return

        # Update size in pixels
        if self.x < 1:
            self.px_x = int(self.img_size[0] * self.x)
        else:
            self.px_x = int(self.x)
        if self.y < 1:
            self.px_y = int(self.img_size[1] * self.y)
        else:
            self.px_y = int(self.y)

    def target_dc(self, dc):
        self.img_size = dc.Size
        target = self.target
        if self.target:
            # Set brushes
            dc.SetPen(self.target_pen)
            dc.SetBrush(self.target_brush)

            # Validate input
            try:
                x, y = float(self.x), float(self.y)
            except ValueError:
                self.reset()
                return

            # Convert sizes to pixels appropriate to given DC
            # TODO: do this for raw pixel entries too
            if x < 1:
                x_c = self.img_size[0] * x
            else:
                x_c = x
            if y < 1:
                y_c = self.img_size[1] * y
            else:
                y_c = y
            r = self.size

            # Draw target
            if target == 1:
                dc.DrawLineList((
                    (x_c, y_c-r, x_c, y_c-5),
                    (x_c, y_c+r, x_c, y_c+5),
                    (x_c-r, y_c, x_c-5, y_c),
                    (x_c+r, y_c, x_c+5, y_c)))
            elif target == 2:
                r2 = 2 * r
                dc.DrawRectangle(x_c-r, y_c-r, r2, r2)
            elif target == 3:
                dc.DrawCircle(x_c, y_c, r)

    def process_dc(self, dc):
        self.target_dc(dc)

    def target_img(self, img):
        # TODO: process opencv image
        return img

    def process_img(self, img):
        return self.target_img(img)


# wx.Frame -------------------------------------------------------------------

class FullscreenFrame(wx.Frame):
    ''' Frame that simulates fullscreen on Show() '''

    def __init__(self, *args, **kwargs):
        kwargs['style'] = 0
        super().__init__(*args, **kwargs)

        def OnKey(event):
            ''' Exit fullscreen on ESC and inform parent frame '''
            if event.GetKeyCode() == wx.WXK_ESCAPE:
                self.GetParent().fullscreen = False
                self.Hide()

        window = wx.Window(self)    # Required to process EVT_KEY_DOWN
        window.Bind(wx.EVT_KEY_DOWN, OnKey)

    def Show(self, show=True):
        super().Show(show)
        if show:
            super().Maximize()


class BasicGui(wx.Frame):
    ''' Simple three-section GUI with image, left sidebar, and bottom bar. '''

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Visible GUI elements
        self.image_window = GuiImage(self)
        self.image_full = FullscreenFrame(self)
        self.image = np.zeros(sz_img, dtype=np.uint8)
        self.sensor_panels = ['settings, color, buffalo']  # TODO
        self.view_panel = ViewPanel(self)
        self.layout = {
            'init_funcs': [],
            'left': [],
            'right': [self.image_window],
            'bottom': [self.view_panel]}

        # Image display
        self.frames = 0
        self.img_start = threading.Event()
        self.img_queue = Queue(2)
        self.img_processes = {'full': [], 'resized': [], 'dc': []}
        self.video_writer = None

        def display_loop():
            ''' Run method for image display thread '''

            img_start = self.img_start
            img_queue = self.img_queue
            image_full = self.image_full
            image_window = self.image_window
            view_panel = self.view_panel

            def display(window, img):
                # Skip frame if resized incorrectly for current window
                dc, sz = wx.ClientDC(window), window.GetSize()
                if sz == (img.shape[1], img.shape[0]):
                    # Draw DC and update display window
                    dc.DrawBitmap(wx.Bitmap.FromBuffer(*sz, img), 0, 0)
                    for process in self.img_processes['dc']:
                        process(dc)
                    window.Update()

            while True:
                img_start.wait()                # Wait for GUI "start"
                sensor_img = img_queue.get()    # Wait for available image
                if sensor_img is None:          # Skip image errors
                    print("Debug: Image queue skipped 'None'")
                    continue

                # Make img available for saving, record frame if recording
                self.image = sensor_img
                if view_panel.save_vid_btn:
                    self.video_writer.write(sensor_img)

                # Full-frame image processing
                for process in self.img_processes['full']:
                    sensor_img = process(sensor_img)

                # Resize to target window
                if view_panel.fullscreen:
                    window = image_full
                else:
                    window = image_window
                display_img = cv2.resize(sensor_img, tuple(window.GetSize()),
                                         interpolation=cv2.INTER_NEAREST)

                # Resized-frame image processing
                for process in self.img_processes['resized']:
                    display_img = process(display_img)

                # Convert to RGB and display
                if is_color(display_img):   # from BGR (OpenCV native format)
                    cvt_method = cv2.COLOR_BGR2RGB
                else:                       # from grayscale
                    cvt_method = cv2.COLOR_GRAY2RGB
                display_img = cv2.cvtColor(display_img, cvt_method)
                wx.CallAfter(display, window, display_img)  # thread-safe
                self.frames += 1

        self.img_thread = threading.Thread(target=display_loop)
        self.img_thread.daemon = True
        self.img_thread.start()

    def Assemble(self, layout=None):
        layout = self.layout or layout

        def add_module(parent, module, padding=pad):
            ''' Add module (panel or sizer) to parent sizer with padding '''
            parent.Add(module)
            parent.AddSpacer(padding)

        def construct_sizer(orientation, modules, padding=pad):
            ''' Build sizer from modules with given orientation and padding '''
            sizer = wx.BoxSizer(orientation)
            if len(modules) > 0:
                if orientation == wx.VERTICAL:
                    sizer.AddSpacer(pad_outer)
                for m in modules[:-1]:
                    add_module(sizer, m, padding)
                add_module(sizer, modules[-1], pad_outer)
            return sizer

        # Initiallize GUI elements
        for func in layout['init_funcs']:
            func()

        # Assemble GUI elements
        left_szr = construct_sizer(wx.VERTICAL, layout['left'])
        bot_szr = construct_sizer(wx.HORIZONTAL, layout['bottom'])
        layout['right'].append(bot_szr)
        right_szr = construct_sizer(wx.VERTICAL, layout['right'], pad_outer)

        # Assemble GUI
        gui_sizer = wx.BoxSizer(wx.HORIZONTAL)
        gui_sizer.AddSpacer(pad_outer)
        add_module(gui_sizer, left_szr, pad_outer)
        add_module(gui_sizer, right_szr, pad_outer)
        self.SetSizerAndFit(gui_sizer)
        self.Show()

    # def AddDevice(self, device):
    #     if self.panels == 'all':
    #         for panel in device.panels:
    #             name, location = panel
    #             self.layout[location].insert(1, panel)
    #     else:
    #         for panel in self.panels:
    #             name, location = panel
    #             if panel in device.panels:
    #                 self.layout[location].insert(1, panel)


class HardwareGui(BasicGui):
    ''' BasicGui with support for adding/removing hardware control panels.
        Stages go on left bar, sensors go on bottom bar. '''

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.panels = {'stages': [], 'sensors': []}

    def update_panels(self):
        ''' Rebuild GUI from self.panels '''
        pass
