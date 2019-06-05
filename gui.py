import cv2
import numpy as np
import queue
import subprocess
import threading
import time
import wx


# Constants -------------------------------------------------------------------

# Math
PI2 = np.pi / 2

# Colored pixels
BLUE_PX = np.uint8((255, 0, 0))         # BGR format for OpenCV / NumPy
GREEN_PX = np.uint8((0, 255, 0))
RED_PX = np.uint8((0, 0, 255))

# wx.Size
PX_PAD = 25
PX_PAD_INNER = 3
PX_PAD_OUTER = 10
SZ_IMAGE = wx.Size(1280, 800)           # (W, H); opposite of NumPy
SZ_THUMB = wx.Size(128, 80)
SZ_BTN = wx.Size(2*PX_PAD, 2*PX_PAD)
SZ1 = wx.Size(2*PX_PAD, PX_PAD)
SZ2 = wx.Size(3*PX_PAD, PX_PAD)
SZ3 = wx.Size(4*PX_PAD, PX_PAD)
HT1 = wx.Size(-1, PX_PAD)               # -1 = default
WD1 = wx.Size(2*PX_PAD, -1)
WD2 = wx.Size(3*PX_PAD, -1)
WD3 = wx.Size(4*PX_PAD, -1)

# wx.GBSpan (for wx.GridBagSizer)
SP1 = wx.GBSpan(1, 1)
SP2 = wx.GBSpan(1, 2)
SP3 = wx.GBSpan(1, 3)

# wx misc
ALIGN_CENTER_RIGHT = wx.ALIGN_RIGHT | wx.ALIGN_CENTER_VERTICAL
CLR_BG = wx.Colour(0, 0, 0).MakeDisabled()


# Helper functions ------------------------------------------------------------

def attrib_name(name):
    ''' Turn a string into an acceptable attribute name '''
    return name.lower().replace(' ', '_')


def get_dir_name(fn):
    return fn[:fn.rfind('/') + 1]


def is_color(img):
    ''' Return True if image contains a color channel, False otherwise '''
    return len(img.shape) == 3


def make_binding(obj, func):
    ''' Set parameter if given a value, update GUI with returned value '''

    def textctrl_binding(event):
        val = to_float(obj.GetValue())
        if isinstance(val, str):
            val = val.rstrip()
            if val == '':
                val = None
        ret = func(val)
        if not (ret is None or isinstance(ret, bool)):
            obj.SetValue(str(ret))

    def item_container_binding(event):
        ret = func(obj.GetSelection())
        if isinstance(ret, (int, float, bool)):
            obj.SetSelection(int(ret))

    if isinstance(obj, wx.TextCtrl):
        binding = textctrl_binding
    elif isinstance(obj, wx.ItemContainerImmutable):
        binding = item_container_binding
    else:
        raise NotImplementedError(
            "Binding not implemented for {}".format(type(obj)))
    return binding


def to_float(value):
    ''' Try to convert string to float; return string if failed '''
    try:
        value = float(value)
    except ValueError:
        pass
    return value


def to_rgb(img):
    ''' Convert grayscale or BGR (OpenCV default) to RGB (wx default) '''
    return cv2.cvtColor(
        img, cv2.COLOR_BGR2RGB if is_color(img) else cv2.COLOR_GRAY2RGB)


def top_px(img, n=1):
    ''' Return top nth pixel from an image '''
    return img.max() if n == 1 else np.partition(img.flatten(), -n)[-n]


def top_px_avg(img, n=3):
    ''' Return average of top n pixels from an image '''
    return img.max() if n == 1 else np.partition(img.flatten(), -n)[-n:].mean()


# Devices ---------------------------------------------------------------------

def test_image(shape=SZ_IMAGE[::-1]):   # [::-1] reverses order for NumPy
    ''' Generate random uint8 image of given shape '''
    return np.random.randint(0, 256, shape, np.uint8)


class GuiDevice(object):
    ''' Mixin class to add GUI panel functionality to a device.
        Inherited by GUI submodules. '''

    def __init__(self, panels={}):
        super().__init__()
        self.panels = panels
        if not hasattr(self, 'available'):
            self.available = True
        if not hasattr(self, 'running'):
            self.running = False

    def make_panel(self, parent, panel_name):
        return self.panels[panel_name](parent, self)

    def make_panels(self, parent):
        built_panels = []
        for panel_name in self.panels:
            built_panels.append(self.make_panel(parent, panel_name))
        return built_panels

    def start(self):
        self.running = True

    def close(self):
        self.running = False


class HybridDevice(GuiDevice):
    ''' Container for multiple interacting GuiDevices. '''

    def __init__(self, devices=[], panels={}):
        super().__init__(panels)
        self.devices = devices
        for device in self.devices:
            self.available &= device.available

    def start(self):
        running = True
        for device in self.devices:
            running &= device.start()
        if not running:
            self.close()
        return running

    def close(self):
        for device in self.devices:
            device.close()
        self.running = False


class GuiSensor(GuiDevice):
    ''' GuiDevice that accepts an image queue '''

    def __init__(self, img_queue, panels={}):
        self.img_queue = img_queue
        super().__init__(panels)


class TestSensor(GuiSensor):
    ''' Test sensor, fills img_queue with random uint8 data '''

    def __init__(self, img_queue, timeout=1):
        super().__init__(img_queue)
        self.timeout = timeout
        self.img_thread = None
        self.start()

    def _img_loop(self):
        put_image = self.img_queue.put
        while self.running:
            try:
                put_image(test_image(), timeout=self.timeout)
            except queue.Full:
                pass

    def start(self):
        self.running = True
        self.img_thread = threading.Thread(target=self._img_loop)
        self.img_thread.daemon = True
        self.img_thread.start()
        return self.running

    def close(self):
        self.running = False
        if self.img_thread:
            self.img_thread.join()
            self.img_thread = None


class TestImgSensor(TestSensor):
    ''' Test sensor, fills img_queue with copies of a hard-coded image. '''

    IMG_PATH = "test.png"

    def _img_loop(self):
        put_image = self.img_queue.put
        while self.running:
            try:
                put_image(
                    cv2.imread(self.IMG_PATH, cv2.IMREAD_ANYDEPTH),
                    timeout=self.timeout)
            except queue.Full:
                pass


# wx.Dialog -------------------------------------------------------------------

# # TODO
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


class TextCtrl(wx.TextCtrl):
    ''' TextCtrl with built-in maximum length, not fully implemented in wx '''

    def __init__(self, *args, length=0, **kwargs):
        super().__init__(*args, **kwargs)
        self.SetMaxLength(length)

    def GetMaxLength(self):
        ''' Method not provided by wx, use attribute instead '''
        return self.MaxLength

    def SetMaxLength(self, length):
        ''' Do wx SetMaxLength() then save length as attribute '''
        super().SetMaxLength(length)
        self.MaxLength = length         # for GetMaxLength

    def SetValue(self, value):
        ''' Truncate string to self.MaxLength before wx SetValue() '''
        if self.MaxLength:
            value = value[:self.MaxLength]
        super().SetValue(value)


# wx.Sizer --------------------------------------------------------------------

class GuiItem():
    ''' Item and layout information for use in wx.GridBagSizer construction.
        Provides defaults and handles wx.GBPosition. '''

    def __init__(self, item, position, span=SP1, flag=0):
        self.item = item
        self.position = wx.GBPosition(position)
        self.span = span
        self.flag = flag


class GuiSizer(wx.GridBagSizer):
    ''' wx.GridBagSizer that accepts list of GuiItems to build itself. '''

    def __init__(self, items=None, hpad=None, vpad=None):
        super().__init__(hpad or PX_PAD_INNER, vpad or PX_PAD_INNER)
        if items is not None:
            self.AddList(items)

    def AddList(self, items):
        for item in items:
            self.Add(item.item, item.position, item.span, item.flag)


# wx.Panel --------------------------------------------------------------------

class GuiPanel(wx.Panel):
    ''' Panel containing GUI elements that can be read/set like attributes
        Also can be passed a device object for GUI to interact with. '''

    def __init__(self, parent, device=None, **kwargs):
        super().__init__(parent, **kwargs)
        self.controls = []      # GUI elements for reset/update/validate
        self.device = device
        self.MakeSizerAndFit(self.MakeLayout())
        self.validate()

    def __getattribute__(self, name):
        ''' Retrieve value of GUI elements instead of elements themselves. '''
        # If attribute "name" is a wx object...
        elem = object.__getattribute__(self, name)
        if isinstance(elem, wx.Object):
            # Return content of TextCtrl, as float if possible
            # Return state of ToggleButton (HACK: as float, but whatever)
            if isinstance(elem, (wx.TextCtrl, wx.ToggleButton)):
                return to_float(elem.GetValue())
            # Return index of Choice, ComboBox, RadioBox
            # HACK: This prevents GetStringSelection, use GetObject for that
            elif isinstance(elem, wx.ItemContainerImmutable):
                return elem.GetSelection()
            # Return text value of StaticText, as float if possible
            elif isinstance(elem, wx.StaticText):
                return to_float(elem.GetLabel())
        # Return anything else as normal
        return elem

    def __setattr__(self, name, value):
        ''' Set value of GUI elements instead of overwriting elements. '''
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

    def GetObject(self, name):
        ''' Bypass custom __getattribute__ to return a wx object. '''
        return object.__getattribute__(self, name)

    def MakeLabel(self):
        ''' Build and return a wx.StaticText from the panel name. '''
        return wx.StaticText(self, label=self.GetName())

    def MakeLayout(self):
        ''' Return list of elements and positions for MakeSizeAndFit.
            Override this to edit the panel layout. '''
        return []

    def MakeSizerAndFit(self, items):
        ''' Similar to SetSizerAndFit, but creates a GuiSizer first. '''
        self.SetSizerAndFit(GuiSizer(items))

    def reset(self, event=None):
        ''' Reset GuiPanel elements to default state. '''
        for control in self.controls:
            if isinstance(control, wx.TextCtrl):
                control.SetValue('')
            elif isinstance(control, wx.ToggleButton):
                control.SetValue(False)
            # elif isinstance(control, wx.ItemContainerImmutable):
            #     control.SetSelection(0)

    def update(self, event=None):
        ''' Refresh GuiPanel elements by triggering their event handlers. '''
        self.reset()
        for control in self.controls:
            if isinstance(control, wx.TextCtrl):
                evt = wx.EVT_TEXT_ENTER
            elif isinstance(control, wx.ToggleButton):
                evt = wx.EVT_TOGGLEBUTTON
            # elif isinstance(control, wx.RadioBox):
            #     evt = wx.EVT_RADIOBOX
            else:
                continue
            event = wx.PyCommandEvent(evt.typeId, control.GetId())
            control.GetEventHandler().ProcessEvent(event)

    def validate(self, event=None):
        ''' Verify device and check for valid input in GuiPanel elements. '''
        ret = True
        if self.device and not self.device.available:
            self.Disable()
            ret = False
        return ret


class HybridPanel(GuiPanel):
    ''' Container panel to combine multiple GuiPanels. '''

    def __init__(self, parent, device=None, panels={}, **kwargs):
        self.panels = panels
        super().__init__(parent, device, **kwargs)

    def MakeLayout(self):
        layout = []
        for panel in self.panel_info:
            built_panel = panel(self, device=self.device)
            self.__setattr__(
                attrib_name(built_panel.GetName() + "_panel"), built_panel)
            layout.append(built_panel)
        return layout

    def MakeSizerAndFit(self, layout, orientation=wx.VERTICAL):
        panel_sizer = wx.BoxSizer(orientation)
        for item in layout:
            panel_sizer.Add(item)
            panel_sizer.AddSpacer(PX_PAD)
        self.SetSizerAndFit(panel_sizer)

    def reset(self, event=None):
        ''' Pass reset events to child GuiPanels '''
        for child in self.GetChildren():
            if isinstance(child, GuiPanel):
                child.reset(event)

    def update(self, event=None):
        ''' Pass update events to child GuiPanels '''
        for child in self.GetChildren():
            if isinstance(child, GuiPanel):
                child.update(event)

    def validate(self, event=None):
        ''' Pass validate events to child GuiPanels '''
        ret = True
        for child in self.GetChildren():
            if isinstance(child, GuiPanel):
                ret &= child.validate(event)
        return ret


class ViewPanel(GuiPanel):
    ''' View options
        Unlike other panels, this panel is tightly integrated with GuiFrame.
        Many functions use self.parent to manipulate GuiFrame directly. '''

    def __init__(self, parent, img_queue, name='View', fps_time=5,
                 **kwargs):
        super().__init__(parent, name=name, **kwargs)
        # Panel management
        self.parent = parent        # Directly manipulate parent frame
        self.device_panels = []     # Panels loaded by last sensor
        parent.Bind(wx.EVT_CLOSE, self.OnClose)     # EVT_CLOSE requires frame
        # Fullscreen
        self.full_frame = FullscreenFrame(
            self, img_queue, parent.img_processes['dc'])
        self.Bind(wx.EVT_SET_FOCUS, self.OnFocus)   # HACK: doesn't work?
        # Save images
        self.img_drn = None
        # Save video
        self.vid_drn = None
        self.vid_frame = 0
        self.vid_n = 0
        self.vid_prefix = ''
        # self.vid_writer = None      # cv2.VideoWriter
        # Sum images
        self.sum_dtype = None
        self.sum_final = None
        self.sum_frames = []
        # FPS (frames per second) counter
        self.fps_time = fps_time
        self.frames = 0
        fps_thread = threading.Thread(target=self.__fps_loop)
        fps_thread.daemon = True
        fps_thread.start()
        # Add processes to parent
        parent.img_processes['full'].extend([self.sum_img, self.save_frame])

    def __fps_loop(self):
        ''' Target process for FPS counter thread '''
        def update(f):
            self.fps = f

        wait = self.parent.img_show.wait
        while True:
            if not self.play_btn:
                wx.CallAfter(update, '-')
            wait()
            f0 = self.frames
            time.sleep(self.fps_time)
            wx.CallAfter(update, str((self.frames - f0) / self.fps_time))

    def MakeLayout(self):
        # Make GUI elements
        source = wx.Choice(self, size=WD2)
        play_btn = wx.ToggleButton(self, label='Start', size=SZ1)
        full_btn = wx.ToggleButton(self, label='Full', size=SZ1)
        img_save_btn = wx.Button(self, label='Save', size=SZ1)
        vid_save_btn = wx.ToggleButton(self, label='Record', size=SZ1)
        sum_img_btn = wx.ToggleButton(self, label='Add', size=SZ1)
        sum_n = TextCtrl(
            self, value='0', size=SZ1, style=wx.TE_PROCESS_ENTER, length=4)
        fps_lbl = wx.StaticText(self, label='FPS ')
        fps = wx.StaticText(self, label='-', size=WD1)

        # Bind elements to functions
        source.Bind(wx.EVT_CHOICE, self.select_source)
        play_btn.Bind(wx.EVT_TOGGLEBUTTON, self.play)
        full_btn.Bind(wx.EVT_TOGGLEBUTTON, self.fullscreen)
        img_save_btn.Bind(wx.EVT_BUTTON, self.save_img)
        vid_save_btn.Bind(wx.EVT_TOGGLEBUTTON, self.save_vid)
        sum_n.Bind(wx.EVT_TEXT_ENTER, self.sum_start)

        # Expose elements as attributes
        self.source = source
        self.play_btn = play_btn
        self.full_btn = full_btn
        self.img_save_btn = img_save_btn
        self.vid_save_btn = vid_save_btn
        self.sum_img_btn = sum_img_btn
        self.sum_n = sum_n
        self.fps = fps

        # Return layout for assembly
        layout = [
            GuiItem(self.MakeLabel(), (0, 0), SP2),
            GuiItem(source, (1, 0), SP2, wx.EXPAND),
            GuiItem(play_btn, (2, 0)),
            GuiItem(full_btn, (2, 1)),
            GuiItem(img_save_btn, (3, 0)),
            GuiItem(vid_save_btn, (3, 1)),
            GuiItem(sum_img_btn, (4, 0)),
            GuiItem(sum_n, (4, 1)),
            GuiItem(fps_lbl, (5, 0), flag=ALIGN_CENTER_RIGHT),
            GuiItem(fps, (5, 1))]
        return layout

    def OnClose(self, event):
        ''' Make sure any open device closes cleanly '''
        if self.device:
            self.device.close()
        event.Skip()    # Continue processing Close event

    def OnFocus(self, event):
        ''' Disable full_btn if focus is no longer on fullscreen_window '''
        self.full_btn = False
        event.Skip()

    def reset(self, event=None):
        if self.full_btn:
            self.full_btn = False
            self.fullscreen()
        if self.play_btn:
            self.play_btn = False
            self.play()
        if self.vid_save_btn:
            self.vid_save_btn = False
            self.save_vid()
        self.sum_img_btn = False
        self.sum_n = 0
        for panel in self.device_panels:
            panel.reset()

    def update(self, event=None):
        for panel in self.device_panels:
            panel.update()

    def validate(self, event=None):
        ret = True
        if not isinstance(self.sum_n, float):
            self.reset()
            ret = False
        else:
            self.sum_n = int(self.sum_n)
        return ret

    # Manage sources -------------------------------
    def add_source(self, name, obj, set_source=False):
        # Append name to GUI, append obj to ClientData for that selection
        source_select = self.GetObject('source')
        source_select.Append(name, obj)
        if set_source:
            self.set_source()

    def add_sources(self, sources, set_source=False):
        if isinstance(sources, list):   # Add each from the list
            for s in sources:
                self.add_source(*s)
        else:
            self.add_source(sources)    # If not actually a list
        if set_source:
            self.set_source()

    def del_source(self, index):
        self.GetObject('source').Delete(index)

    def select_source(self, event=None):
        parent = self.parent
        layout = parent.layout
        img_queue = parent.img_queue
        source_index = self.source
        # Reset ToggleButtons (not source selection)
        self.reset()
        # Remove old panels
        for old_panel in self.device_panels:
            old_panel.Destroy()
            for i, gui_panel in enumerate(layout['bottom']):
                if isinstance(old_panel, type(gui_panel)):
                    layout['bottom'].pop(i)
        self.device_panels = []
        # Remove old device
        if self.device:                     # Remove device
            self.device.close()
            self.device = None
        while not img_queue.empty():        # Purge any queued frames
            img_queue.get(False)
        # Create new device
        new_device = self.GetObject('source').GetClientData(source_index)
        try:
            self.device = new_device(img_queue)
        except Exception as e:
            print("Error: couldn't create sensor object. Details:\n", e)
            self.del_source(source_index)   # Remove device from list on fail
            return
        # Add new panels
        self.device_panels = self.device.make_panels(parent)
        for i, new_panel in enumerate(self.device_panels):
            layout['bottom'].insert(i+1, new_panel)
        # Reassemble GUI
        parent.Assemble()
        self.update()

    def set_source(self, i=0):
        self.GetObject('source').SetSelection(i)
        self.select_source()

    # Manage display -------------------------------
    def sum_start(self, event=None):
        self.sum_img_button = self.validate()

    def sum_img(self, img):
        ''' Rolling sum over self.sum_n frames '''
        if self.sum_img_btn:
            # Caching, saves a few lookups (probably useless)
            sum_n = self.sum_n
            sum_final = self.sum_final
            sum_dtype = self.sum_dtype
            sum_frames = self.sum_frames
            # Reset self.sum_final if format has changed
            if sum_final is None                \
               or isinstance(sum_n, str)        \
               or sum_n < 1                     \
               or sum_final.shape != img.shape  \
               or sum_dtype != img.dtype:
                self.sum_dtype = img.dtype
                self.sum_final = img.astype(np.float64)
                self.sum_frames = [img.copy()]
            else:
                # Add new image to self.sum_final and self.sum_frames
                sum_final += img.astype(np.float64)
                sum_frames.append(img.copy())
                # Subtract frames if too many
                while len(sum_frames) > sum_n:
                    sum_final -= sum_frames.pop(0)
                # Return as appropriate dtype
                # If original was 8-bit, try to preserve bit depth:
                #     - if max > 255, scale up to 65535 and return as 16-bit
                #     - if max <= 255, don't scale, return as 8-bit
                # If original was 16-bit, avoid overrun:
                #     - if max > 65535, scale down to 65535, return as 16-bit
                new_dtype = np.uint16
                mx = sum_final.max()
                if mx > 65535 or (img.dtype == np.uint8 and mx > 255):
                    f = 65535 / mx
                    img = sum_final * f
                elif img.dtype == np.uint8:
                    new_dtype = np.uint8
                img = img.astype(new_dtype)
        else:
            self.sum_dtype = None
            self.sum_final = None
            self.sum_frames = []
        return img

    def fullscreen(self, event=None):
        ''' Show/hide fullscreen frame '''
        self.full_frame.ShowFullScreen(self.full_btn)

    def play(self, event=None):
        flag = self.parent.img_show
        if self.play_btn:
            flag.set()
        else:
            flag.clear()

    def save_img(self, event=None):
        ''' Save still image via dialog '''
        if isinstance(self.parent.image, np.ndarray):
            img = self.parent.image.copy()
            ext = '.png'
            dialog = wx.FileDialog(
                self, 'Save image', self.img_drn or '', 'image.png', '*'+ext,
                wx.FD_SAVE)
            if dialog.ShowModal() == wx.ID_OK:
                fn = dialog.GetPath()
                if fn[-4:].lower() != ext:
                    fn += ext
                cv2.imwrite(fn, img, (cv2.IMWRITE_PNG_COMPRESSION, 0))
                self.img_drn = get_dir_name(fn)
        else:
            print("Error: No image available.")

    def save_frame(self, img):
        # HACK: save series of images instead of avi
        # if self.video_writer:
        #     if not is_color(img):
        #         img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
        #     self.video_writer.write(img)
        if self.vid_save_btn and self.vid_drn:
            fn = self.vid_prefix + str(self.vid_frame) + '.png'
            cv2.imwrite(fn, img, (cv2.IMWRITE_PNG_COMPRESSION, 0))
            self.vid_frame += 1
        return img

    def save_vid(self, event=None):
        ''' Start/stop recording, with save dialog '''
        # HACK: save series of images instead of avi
        if self.play_btn and self.vid_save_btn:
            flag = self.parent.img_show
            flag.clear()            # Pause capture
            dialog = wx.DirDialog(self, 'Save frames', self.vid_drn or '')
            if dialog.ShowModal() == wx.ID_OK:
                self.vid_drn = dialog.GetPath()
                self.vid_frame = 1
                self.vid_n += 1
                self.vid_prefix = self.vid_drn + '/' + str(self.vid_n) + '_'
            else:
                self.vid_save_btn = False
        #     fn = FileDialog('Save video', '.avi', save=True)
        #     if fn:                  # Start recording
        #         self.vid_drn = get_dir_name(fn)
        #         self.vid_frame = 1
        #         # codec = cv2.VideoWriter_fourcc('M', 'J', 'P', 'G')
        #         # fps = 10
        #         # shape = parent.image.shape[:2][::-1]
        #         # self.video_writer = cv2.VideoWriter(fn, codec, fps, shape)
        #     else:                   # Cancel recording
        #         self.vid_save_btn = False
        # else:                   # Finish recording
        #     time.sleep(0.5)     # Wait for img pipeline (unnecessary?)
        #     if self.vid_writer:
        #         self.vid_writer.release()
        #     self.vid_writer = None
            flag.set()              # Continue capture
        else:
            self.vid_save_btn = False


# Sensor templates

# class MetricsPanel(GuiPanel):
#     ''' Metrics readout panel
#         Update values (not display!) by editing dict 'values'
#         Update display with most recent values with update()
#         Update list of values to be displayed with build()
#         Start regular updates by passing an Event flag to start()
#         Stop regular updates with stop() '''
#
#     def __init__(self, *args, name='Metrics', **kwargs):
#         if 'values' in kwargs:
#             self.values = kwargs.pop('values')
#         else:
#             self.values = {}
#         super().__init__(*args, name=name, **kwargs)
#         self.build()
#         self.updating = False
#
#     def build(self):
#         self.display = {}
#         new_items = [GuiItem(self.MakeLabel(), (0, 0), SP2)]
#         for name in self.values:
#             # Replace 'None' with '-' just to keep it clean
#             v = self.values[name]
#             if v is None:
#                 v = '-'
#             else:
#                 v = str(v)
#             # Build display
#             i = len(new_items)
#             label = wx.StaticText(self, label=name + ': ')
#             value = wx.StaticText(self, label=v)
#             new_items.extend([
#                 GuiItem(label, (i, 0), flag=ALIGN_CENTER_RIGHT),
#                 GuiItem(value, (i, 1))])
#             self.display[name] = value
#         self.MakeSizerAndFit(*new_items)
#
#     def update(self):
#         for name in self.values:
#             if name in self.display:
#                 self.display[name].SetValue(str(self.values[name]))
#
#     def start(self, update_flag):
#         def __update_loop(self):
#             while True:
#                 update_flag.wait()
#                 self.update()
#                 update_flag.clear()
#
#         self.updating = threading.Thread(
#             target=self.__update_loop, args=(update_flag, ))
#         self.updating.daemon = True
#         self.updating.start()
#
#     def stop(self):
#         if self.updating:
#             self.updating.terminate()
#         self.updating = False


class RoiPanel(GuiPanel):
    ''' ROI (Region Of Interest) control '''

    def __init__(self, *args, name='ROI', **kwargs):
        super().__init__(*args, name=name, **kwargs)

    def MakeLayout(self):
        start_lbl = wx.StaticText(self, label='Start')
        end_lbl = wx.StaticText(self, label='End')
        x_lbl = wx.StaticText(self, label='x')
        x = TextCtrl(self, size=SZ1, length=6, style=wx.TE_PROCESS_ENTER)
        w = TextCtrl(self, size=SZ1, length=6, style=wx.TE_PROCESS_ENTER)
        y_lbl = wx.StaticText(self, label='y')
        y = TextCtrl(self, size=SZ1, length=6, style=wx.TE_PROCESS_ENTER)
        h = TextCtrl(self, size=SZ1, length=6, style=wx.TE_PROCESS_ENTER)
        reset_btn = wx.Button(self, label='Reset', size=SZ1)
        load_btn = wx.Button(self, label='Load', size=SZ1)

        x.Bind(wx.EVT_TEXT_ENTER, self.set_roi)
        y.Bind(wx.EVT_TEXT_ENTER, self.set_roi)
        w.Bind(wx.EVT_TEXT_ENTER, self.set_roi)
        h.Bind(wx.EVT_TEXT_ENTER, self.set_roi)
        reset_btn.Bind(wx.EVT_BUTTON, self.reset)
        # load_btn.Bind(wx.EVT_BUTTON, self.set_roi)    # TODO: save/load state
        load_btn.Disable()

        self.reset_btn = reset_btn
        self.load_btn = load_btn
        self.x = x
        self.w = w
        self.y = y
        self.h = h
        self.controls.extend([reset_btn, load_btn, x, w, y, h])
        self.reset()

        layout = [
            GuiItem(self.MakeLabel(), (0, 0), SP3),
            GuiItem(start_lbl, (1, 1), flag=wx.ALIGN_CENTER_HORIZONTAL),
            GuiItem(end_lbl, (1, 2), flag=wx.ALIGN_CENTER_HORIZONTAL),
            GuiItem(x_lbl, (2, 0), flag=ALIGN_CENTER_RIGHT),
            GuiItem(x, (2, 1)),
            GuiItem(w, (2, 2)),
            GuiItem(y_lbl, (3, 0), flag=ALIGN_CENTER_RIGHT),
            GuiItem(y, (3, 1)),
            GuiItem(h, (3, 2)),
            GuiItem(reset_btn, (4, 1)),
            GuiItem(load_btn, (4, 2))]
        return layout

    def get_roi(self, event=None):
        roi = self.device.roi(None)
        if roi:
            self.x, self.y, self.w, self.h = roi
        else:
            self.reset()

    def set_roi(self, event=None):
        if not self.validate() or not self.device or not self.device.running:
            return
        self.x, self.y, self.w, self.h = self.device.roi(
            (self.x, self.y, self.w, self.h))

    def reset(self, event=None):
        self.x = self.y = 0.0
        self.w = self.h = 1.0
        self.set_roi()

    def update(self, event=None):
        self.get_roi()

    def validate(self, event=None):
        ret = True
        x, y = self.x, self.y
        try:
            self.x = np.clip(x, 0, 1)
            self.y = np.clip(y, 0, 1)
            self.w = np.clip(self.w, x, 1)
            self.h = np.clip(self.h, y, 1)
        except (ValueError, TypeError):
            self.reset()
            ret = False
        return ret


class TextCtrlPanel(GuiPanel):
    ''' Provides build_settings as a helper method to create control panels
        from a list of settings. '''

    def build_textctrls(self, textctrls, start=(0, 0), size=SZ1, length=5):
        ''' Build column of functional TextCtrls from a list of parameters.
            textctrls: List of parameter tuples for which to build controls:
                (label, units, function)
            start: (row, column) tuple of first element
            Sets panel attributes, binds functions, and returns GUI layout:
                [(StaticText label, TextCtrl value, StaticText units)...] '''

        if not isinstance(textctrls, (tuple, list)):
            raise TypeError(
                "TextSettingsPanel.build_textctrls requires a tuple or list.")

        i, j = start
        layout, controls = [], []
        for param, units, func in textctrls:
            # Create GUI layout
            label = wx.StaticText(self, label=param)
            field = TextCtrl(
                self, size=size, value='', length=length,
                style=wx.TE_PROCESS_ENTER)
            field.SetMaxLength(length)
            units = wx.StaticText(self, label=units)
            # Add GUI layout
            layout.extend([
                GuiItem(label, (i, j), flag=ALIGN_CENTER_RIGHT),
                GuiItem(field, (i, j+1), flag=wx.EXPAND),
                GuiItem(units, (i, j+2), flag=wx.ALIGN_CENTER_VERTICAL)])
            # Bind function to ctrl
            field.Bind(wx.EVT_TEXT_ENTER, make_binding(field, func))
            # Expose ctrl as panel attribute
            self.__setattr__(attrib_name(param), field)
            controls.append(field)
            i += 1
        self.controls.extend(controls)
        return layout


class CapturePanel(TextCtrlPanel):
    ''' Basic capture settings panel, example use of TextCtrlPanel '''

    def __init__(self, *args, name='Capture', **kwargs):
        super().__init__(*args, name=name, **kwargs)

    def MakeLayout(self):
        textctrls = [
            ('Exposure', 'us', self.device.exposure),
            ('Gain', '', self.device.gain),
            ('Framerate', 'fps', self.device.fps)]
        layout = [
            GuiItem(self.MakeLabel(), (0, 0), SP3),
            *self.build_textctrls(textctrls, (1, 0), SZ2, 10)]
        return layout


# Image processing

class ColorPanel(GuiPanel):
    ''' Color processing '''

    RNG8 = np.arange(0, 256)    # Pixel values for range_img

    def __init__(self, *args, name='Color', **kwargs):
        super().__init__(*args, name=name, **kwargs)
        self.gamma_lut = None
        self.sat_map = None
        self.GetParent().img_processes['resized'].append(self.process_img)

    def MakeLayout(self):
        colormaps = (               # defined to match OpenCV indices
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
        colormap = wx.Choice(self, choices=colormaps)
        colormap.SetSelection(1)     # no colormap
        range_btn = wx.ToggleButton(self, label='Range', size=SZ2)
        range_val = TextCtrl(
            self, value='255', size=SZ1, length=3, style=wx.TE_PROCESS_ENTER)
        gamma_btn = wx.ToggleButton(self, label='Gamma', size=SZ2)
        gamma_val = TextCtrl(
            self, value='2.2', size=SZ1, length=5, style=wx.TE_PROCESS_ENTER)
        sat_btn = wx.ToggleButton(self, label='Highlight', size=SZ2)
        sat_val = TextCtrl(
            self, value='255', size=SZ1, length=3, style=wx.TE_PROCESS_ENTER)

        range_btn.Bind(wx.EVT_TOGGLEBUTTON, self.set_range)
        range_val.Bind(wx.EVT_TEXT_ENTER, self.set_range)
        gamma_btn.Bind(wx.EVT_TOGGLEBUTTON, self.set_gamma)
        gamma_val.Bind(wx.EVT_TEXT_ENTER, self.set_gamma)
        sat_btn.Bind(wx.EVT_TOGGLEBUTTON, self.set_sat)
        sat_val.Bind(wx.EVT_TEXT_ENTER, self.set_sat)

        self.colormap = colormap
        self.range_btn = range_btn
        self.range_val = range_val
        self.gamma_btn = gamma_btn
        self.gamma_val = gamma_val
        self.sat_btn = sat_btn
        self.sat_val = sat_val
        self.controls.extend([
            colormap, range_btn, range_val, gamma_btn, gamma_val, sat_btn,
            sat_val])

        self.set_gamma()

        layout = [
            GuiItem(self.MakeLabel(), (0, 0), SP2),
            GuiItem(colormap, (1, 0), SP2, wx.EXPAND),
            GuiItem(range_btn, (2, 0)),
            GuiItem(range_val, (2, 1)),
            GuiItem(gamma_btn, (3, 0)),
            GuiItem(gamma_val, (3, 1)),
            GuiItem(sat_btn, (4, 0)),
            GuiItem(sat_val, (4, 1))]
        return layout

    def set_range(self, event=None):
        ''' Validate dynamic range value '''
        if self.range_btn:
            try:
                v = np.clip(int(self.range_val), 0, 255)
            except ValueError:
                v = 255
            self.range_val = v

    def set_gamma(self, event=None):
        ''' Validate gamma value and create look-up table (LUT) '''
        if self.gamma_btn:
            # Validate
            try:
                gamma = np.clip(self.gamma_val, 1.0, 10.0)
            except ValueError:
                gamma = 2.2
            # Create look-up table (LUT)
            self.gamma_lut = (np.arange(0, 1, 1/256) ** (1/gamma) * 255 + 0.5
                              ).astype(np.uint8)
            # Update displayed value
            self.gamma_val = gamma

    def set_sat(self, event=None):
        ''' Validate dynamic range value '''
        if self.sat_btn:
            try:
                v = np.clip(int(self.sat_val), 0, 255)
            except ValueError:
                v = 255
            self.sat_val = v

    def is_sat(self):
        ''' Check if saturated pixel highlighting is active and ready. '''
        return self.sat_btn and isinstance(self.sat_map, np.ndarray)

    def colormap_img(self, img):
        ''' Apply selected colormap by index '''
        colormap = self.colormap - 2
        if colormap > -1:                           # Colormap
            img = cv2.applyColorMap(img, colormap)
        elif colormap == -2 and is_color(img):      # Force gray
            img = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        return img

    def range_img(self, img):
        ''' Stretch dynamic range to be from 0 to self.range_val '''
        if self.range_btn:
            img -= img.min()
            if self.is_sat():
                mx = img[~self.sat_map].max()       # Ignore saturated pixels
            else:
                mx = img.max()
            if mx:
                img = cv2.LUT(
                    img, (self.RNG8 * self.range_val / mx).astype(np.uint8))
        return img

    def gamma_img(self, img):
        ''' Apply gamma curve using lookup table '''
        if self.gamma_btn:
            img = cv2.LUT(img, self.gamma_lut)
        return img

    def find_sat_img(self, img):
        ''' Find and save locations of pixels above given threshold '''
        if self.sat_btn:
            self.sat_map = img >= self.sat_val
            if is_color(img):
                self.sat_map = np.logical_or.reduce(self.sat_map, 2)
        return img

    def apply_sat_img(self, img):
        ''' Make previously-saved pixels red '''
        if self.is_sat():
            if not is_color(img):
                img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
            img[self.sat_map] = RED_PX
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

    def __init__(self, *args, name='Flat field', **kwargs):
        self.ff = None      # Flat frame
        super().__init__(*args, name=name, **kwargs)
        # Always do flat-frame first!
        self.GetParent().img_processes['full'].insert(0, self.process_img)

    def MakeLayout(self):
        SZ_FF = wx.Size(2.5*PX_PAD, PX_PAD)
        thumb = ImageWindow(self, size=SZ_THUMB)
        save = wx.Button(self, label='Save', size=SZ_FF)
        apply = wx.ToggleButton(self, label='Apply', size=SZ_FF)

        save.Bind(wx.EVT_BUTTON, self.save)
        apply.Bind(wx.EVT_TOGGLEBUTTON, self.validate)

        self.save = save
        self.apply = apply
        self.thumb = thumb
        self.controls.extend([save, apply, thumb])

        layout = [
            GuiItem(self.MakeLabel(), (0, 0), SP2),
            GuiItem(thumb, (1, 0), SP2, wx.ALIGN_CENTER),
            GuiItem(save, (2, 0)),
            GuiItem(apply, (2, 1))]
        return layout

    def save(self, event=None):
        ''' Update flat field and thumbnail '''
        # Save copy of camera image
        ff = self.GetParent().image.copy()
        self.ff = ff
        # Convert to 8-bit for thumbnail display
        if ff.dtype == np.uint16:
            ff = (ff.copy() >> 8).astype(np.uint8)
        # Resize to thumbnail window and convert to RGB
        self.thumb.image = to_rgb(cv2.resize(ff, tuple(SZ_THUMB)))
        # Display thumbnail
        self.thumb.Refresh()

    def reset(self, event=None):
        self.apply = False
        self.thumb.image = None
        self.thumb.Refresh()

    def validate(self, event=None):
        ret = True
        if self.ff is None:
            self.reset()
            ret = False
        return ret

    def flatfield_img(self, img):
        if self.apply:
            # Cancel if image size or color depth has changed
            if self.ff.shape != img.shape or self.ff.dtype is not img.dtype:
                self.reset()
            else:
                img = cv2.subtract(img, self.ff)    # clips between 0-255
        return img

    def process_img(self, img):
        return self.flatfield_img(img)


class FringePanel(GuiPanel):
    ''' Controls related to interference fringes '''

    def __init__(self, *args, name='Fringes', **kwargs):
        super().__init__(*args, name=name, **kwargs)
        self.GetParent().img_processes['resized'].append(self.process_img)
        self.dc_mask = 2    # pixels
        self.fringe_data = []
        self.fringe_flag = threading.Event()
        fringe_thread = threading.Thread(target=self.__fringe_loop)
        fringe_thread.daemon = True
        fringe_thread.start()

    def MakeLayout(self):
        draw_n = TextCtrl(
            self, size=SZ1, length=4, style=wx.TE_PROCESS_ENTER)
        draw_btn = wx.ToggleButton(self, label='Draw', size=SZ1)
        fringe_btn = wx.ToggleButton(self, label='Analyze', size=SZ2)
        fringe_count_lbl = wx.StaticText(self, label='Count')
        fringe_count = wx.StaticText(self, label='-')
        fringe_tilt_lbl = wx.StaticText(self, label='Tilt')
        fringe_tilt = wx.StaticText(self, label='-')
        fringe_contrast_lbl = wx.StaticText(self, label='Contrast')
        fringe_contrast = wx.StaticText(self, label='-')

        draw_n.Bind(wx.EVT_TEXT_ENTER, self.draw_start)
        fringe_btn.Bind(wx.EVT_TOGGLEBUTTON, self.fringe_start)

        self.draw_n = draw_n
        self.draw_btn = draw_btn
        self.fringe_btn = fringe_btn
        self.fringe_count = fringe_count
        self.fringe_tilt = fringe_tilt
        self.fringe_contrast = fringe_contrast
        self.controls.extend([draw_n, draw_btn, fringe_btn])

        layout = [
            GuiItem(self.MakeLabel(), (0, 0), SP2),
            GuiItem(draw_n, (1, 0)),
            GuiItem(draw_btn, (1, 1)),
            GuiItem(fringe_btn, (2, 0), SP2, flag=wx.EXPAND),
            GuiItem(fringe_count_lbl, (3, 0), flag=wx.ALIGN_RIGHT),
            GuiItem(fringe_count, (3, 1)),
            GuiItem(fringe_tilt_lbl, (4, 0), flag=wx.ALIGN_RIGHT),
            GuiItem(fringe_tilt, (4, 1)),
            GuiItem(fringe_contrast_lbl, (5, 0), flag=wx.ALIGN_RIGHT),
            GuiItem(fringe_contrast, (5, 1))]
        return layout

    def draw_start(self, event=None):
        self.draw_btn = True

    def fringe_start(self, event=None):
        if self.fringe_btn:
            self.fringe_flag.set()
        else:
            self.fringe_flag.clear()

    def validate(self, event=None):
        ret = True
        if not isinstance(self.draw_n, float):
            self.reset()
            ret = False
        return ret

    def __fringe_loop(self):
        def pretty(n):
            return str(n)[:6]

        def update(count='-', contrast='-', tilt='-'):
            self.fringe_count = pretty(count)
            self.fringe_tilt = pretty(tilt)
            self.fringe_contrast = pretty(contrast)

        wait = self.fringe_flag.wait
        while True:
            count = contrast = tilt = 0
            if not self.fringe_btn:
                wx.CallAfter(update)
            wait()
            time.sleep(1.)
            for n, c, t in self.fringe_data:
                count += n
                contrast += c
                tilt += t
            if count:
                c = len(self.fringe_data)
                wx.CallAfter(update, count/c, contrast/c, tilt/c)
                self.fringe_data = []

    def fringe_img(self, img):
        if self.fringe_btn:
            # TODO: color images
            if is_color(img):
                self.fringe_btn = False
            else:
                # Smoothing
                img2 = cv2.GaussianBlur(img, (0, 0), 3)

                # Fringe contrast
                h, w = img2.shape
                x, y, r = int(w/2), int(h/2), int(w/5)
                chunk = img2[x-r:x+r, y-r:y+r]
                contrast = (chunk.max() - chunk.min()) / 255

                # Fringe count / tilt
                # DFT
                fft = np.fft.fftshift(np.abs(np.fft.rfft2(img2)))
                # DC mask
                h, w = fft.shape
                x_c, y_c, dc = int(w/2), int(h/2), self.dc_mask
                fft[y_c-dc:y_c+dc, x_c-dc:x_c+dc] = 0
                # Find peak
                y_max, x_max = np.unravel_index(fft.argmax(), fft.shape)
                x_dist, y_dist = x_max - x_c, y_max - y_c
                # Count
                n = np.sqrt(x_dist*x_dist + y_dist*y_dist)
                # Tilt
                tilt = np.degrees(y_dist/x_dist + np.pi) if x_dist else 90.0

                # Save results
                self.fringe_data.append((n, contrast, tilt))
        return img

    def draw_img(self, img):
        if self.draw_btn:
            n = self.draw_n
            if isinstance(n, float):
                h, w = img.shape[:2]
                col = int(w/2)
                row = d = int(h/(n+1) + 0.5)
                px = GREEN_PX if is_color(img) else 255
                for i in range(int(n)):
                    img[row, :col] = px
                    row += d
            else:
                self.draw_btn = False
                self.draw_n = ''
        return img

    def process_img(self, img):
        for process in (self.draw_img, self.fringe_img):
            img = process(img)
        return img


class TargetPanel(GuiPanel):
    ''' Target overlay '''

    def __init__(self, *args, name='Target', **kwargs):
        super().__init__(*args, name=name, **kwargs)
        self.img_size = SZ_IMAGE  # Updated in process_img / process_dc

        # These can't be initialized at the class level...
        self.target_pen = wx.Pen((0, 200, 0), 2)  # Lime green
        self.target_brush = wx.Brush((0, 0, 0), wx.BRUSHSTYLE_TRANSPARENT)
        self.reset()
        self.GetParent().img_processes['dc'].append(self.process_dc)

    def MakeLayout(self):
        targets = ('no target', 'crosshair', 'box', 'circle')
        target = wx.Choice(self, choices=targets)
        size_lbl = wx.StaticText(self, label='Size ')
        size = TextCtrl(self, size=SZ1, length=4, style=wx.TE_PROCESS_ENTER)
        reset_btn = wx.Button(
            self, label='Reset', size=SZ1, style=wx.BU_EXACTFIT)
        orig_lbl = wx.StaticText(self, label='Origin ')
        x = TextCtrl(self, size=SZ1, length=4, style=wx.TE_PROCESS_ENTER)
        y = TextCtrl(self, size=SZ1, length=4, style=wx.TE_PROCESS_ENTER)
        px_lbl = wx.StaticText(self, label='x, y ')
        px_x = wx.StaticText(self, style=wx.ALIGN_RIGHT)
        px_y = wx.StaticText(self, style=wx.ALIGN_RIGHT)

        reset_btn.Bind(wx.EVT_BUTTON, self.reset)
        for elem in (x, y, size):
            elem.Bind(wx.EVT_TEXT_ENTER, self.set_size)

        self.target = target
        self.size = size
        self.x = x
        self.y = y
        self.px_x = px_x
        self.px_y = px_y
        self.reset_btn = reset_btn
        self.controls.extend([target, size, x, y, px_x, px_y, reset_btn])

        layout = [
            GuiItem(self.MakeLabel(), (0, 0), SP3),
            GuiItem(target, (1, 0), SP3, wx.EXPAND),
            GuiItem(size_lbl, (2, 0), flag=ALIGN_CENTER_RIGHT),
            GuiItem(size, (2, 1), flag=wx.EXPAND),
            GuiItem(reset_btn, (2, 2), flag=wx.EXPAND),
            GuiItem(orig_lbl, (3, 0), flag=ALIGN_CENTER_RIGHT),
            GuiItem(x, (3, 1), flag=wx.EXPAND),
            GuiItem(y, (3, 2), flag=wx.EXPAND),
            GuiItem(px_lbl, (4, 0), flag=ALIGN_CENTER_RIGHT),
            GuiItem(px_x, (4, 1), flag=ALIGN_CENTER_RIGHT | wx.EXPAND),
            GuiItem(px_y, (4, 2), flag=ALIGN_CENTER_RIGHT | wx.EXPAND)]
        return layout

    def reset(self, event=None):
        self.target = 0
        self.x = '0.5'
        self.y = '0.5'
        self.size = '20'
        self.set_size()

    def set_size(self, event=None):
        # Validate input
        for v in (self.x, self.y, self.size):
            if isinstance(v, str):
                self.reset()
                return

        # Update size in pixels
        w, h = self.img_size
        x = self.x
        self.px_x = int(w * x) if x < 1 else int(x)
        y = self.y
        self.px_y = int(h * y) if y < 1 else int(y)

    def target_dc(self, dc):
        self.img_size = dc.Size
        target = self.target
        if target:
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
            x_c = self.img_size[0] * x if x < 1 else x
            y_c = self.img_size[1] * y if y < 1 else y
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
            else:   # target == 3:
                dc.DrawCircle(x_c, y_c, r)

    def process_dc(self, dc):
        self.target_dc(dc)

    def target_img(self, img):
        # TODO: process opencv image
        return img

    def process_img(self, img):
        return self.target_img(img)


# wx.Window ------------------------------------------------------------------

class ImageWindow(wx.Window):
    ''' Basic wx.Window for painting images '''

    def __init__(self, parent, image=None, size=SZ_IMAGE, **kwargs):
        super().__init__(parent, size=size, **kwargs)
        self.image = image
        self.SetBackgroundColour(CLR_BG)
        self.SetMinClientSize(size)
        self.Bind(wx.EVT_PAINT, self.OnPaint)

    def OnPaint(self, event):
        ''' Draw image to GUI '''
        if self.image is not None:
            dc = wx.PaintDC(self)
            dc.DrawBitmap(
                wx.Bitmap.FromBuffer(*self.GetSize(), self.image), 0, 0)


class VideoWindow(ImageWindow):
    ''' Subclass of ImageWindow for rapidly painting images '''

    def __init__(self, parent, img_queue, dc_processes=[], size=SZ_IMAGE,
                 **kwargs):
        super().__init__(parent, size=size, **kwargs)
        self.dc_processes = dc_processes
        self.img_queue = img_queue

    def OnPaint(self, event):
        ''' Get image from queue and draw '''
        try:
            img = self.img_queue.get(timeout=0.1)
        except queue.Empty:
            return
        # Skip frame if not resized properly (window recently changed size)
        size = self.GetSize()
        if size == img.shape[:2][::-1]:     # Reverse (h, w) from numpy to wx
            # Draw image and update
            dc = wx.PaintDC(self)
            dc.DrawBitmap(wx.Bitmap.FromBuffer(*size, img), 0, 0)
            for process in self.dc_processes:
                process(dc)


# wx.Frame -------------------------------------------------------------------

class FullscreenFrame(wx.Frame):
    ''' Frame that simulates fullscreen on Show() '''

    def __init__(self, parent, img_queue, dc_processes=[], style=0, **kwargs):
        super().__init__(parent, style=style, **kwargs)
        # Image display
        self.img_window = VideoWindow(self, img_queue, dc_processes)
        self.img_window.Bind(wx.EVT_KEY_DOWN, self.OnKey)

    def OnKey(self, event):
        ''' Exit fullscreen on ESC and inform parent frame '''
        if event.GetKeyCode() == wx.WXK_ESCAPE:
            self.GetParent().full_btn = False   # HACK: EVT_SET_FOCUS broken?
            self.Hide()

    def ShowFullScreen(self, show=True):
        ''' Show in fullscreen mode and disable screensaver, or the reverse '''
        if show:
            self.Maximize()
        subprocess.run(
            ["gsettings", "set", "org.gnome.desktop.screensaver",
             "idle-activation-enabled", str(bool(show)).lower()])
        super().ShowFullScreen(show)


class GuiFrame(wx.Frame):
    ''' Simple three-section GUI with image, left sidebar, and bottom bar.
        Many functions are tightly integrated with ViewPanel. '''

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Image control
        self.img_show = threading.Event()
        self.img_queue = queue.Queue(1)
        self.img_processes = {
            'full': [],
            'resized': [],
            'dc': []}
        self.display_queue = queue.Queue(1)
        # GUI elements
        self.image = np.zeros(SZ_IMAGE, dtype=np.uint8)
        self.img_window = VideoWindow(
            self, self.display_queue, self.img_processes['dc'])
        self.view_panel = ViewPanel(self, self.display_queue)
        # TODO: Panel requests
        # self.panel_requests = {'sensor': 'all', 'stage': 'all'}
        self.layout = {
            'left': [],
            'right': [self.img_window],
            'bottom': [self.view_panel]}
        # Start display thread
        self.img_thread = threading.Thread(target=self.__display_loop)
        self.img_thread.daemon = True
        self.img_thread.start()

    def __display_loop(self):
        ''' Run method for image display thread '''
        # Caching (avoids extra lookups, probably useless)
        display_put = self.display_queue.put
        img_window = self.img_window
        img_processes = self.img_processes
        img_get = self.img_queue.get
        wait = self.img_show.wait
        view_panel = self.view_panel
        full_window = view_panel.full_frame.img_window
        while True:
            # Get image once available
            wait()
            sensor_img = img_get()
            # Process full-frame image
            for process in img_processes['full']:
                sensor_img = process(sensor_img)
            # Save a copy for other functions to access
            self.image = sensor_img.copy()
            # Convert to 8-bit
            if sensor_img.dtype == np.uint16:
                sensor_img = (sensor_img >> 8).astype(np.uint8)
            # Get target window and resize
            window = full_window if view_panel.full_btn else img_window
            display_img = cv2.resize(sensor_img, tuple(window.GetSize()))
            # Process resized image
            for process in img_processes['resized']:
                display_img = process(display_img)
            # Send to window as RGB
            window.Refresh()
            display_put(to_rgb(display_img))
            view_panel.frames += 1

    def Assemble(self):

        def add_module(parent, module, padding=PX_PAD):
            ''' Add module (panel or sizer) to parent sizer with padding '''
            parent.Add(module)
            parent.AddSpacer(padding)

        def construct_panel(orientation, modules, padding=PX_PAD):
            ''' Build sizer from modules with given orientation and padding '''
            sizer = wx.BoxSizer(orientation)
            if len(modules) > 0:
                if orientation == wx.VERTICAL:
                    sizer.AddSpacer(PX_PAD_OUTER)
                for module in modules[:-1]:
                    add_module(sizer, module, padding)
                add_module(sizer, modules[-1], PX_PAD_OUTER)
            return sizer

        # Assemble GUI elements
        layout = self.layout
        gui_sizer = wx.BoxSizer(wx.HORIZONTAL)
        left_szr = construct_panel(wx.VERTICAL, layout['left'])
        bot_szr = construct_panel(wx.HORIZONTAL, layout['bottom'])
        layout['right'].append(bot_szr)
        right_szr = construct_panel(wx.VERTICAL, layout['right'], PX_PAD_OUTER)
        layout['right'].pop()   # allow bot_szr to be deleted on Assemble()
        # Assemble GUI
        gui_sizer.AddSpacer(PX_PAD_OUTER)
        add_module(gui_sizer, left_szr, PX_PAD_OUTER)
        add_module(gui_sizer, right_szr, PX_PAD_OUTER)
        self.SetSizerAndFit(gui_sizer, deleteOld=True)
        self.Layout()   # Sometimes doesn't trigger in SetSizerAndFit?
        self.Show()
