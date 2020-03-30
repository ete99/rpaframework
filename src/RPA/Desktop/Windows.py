import json
import logging
import os
import platform
import re
import subprocess

from pathlib import Path
from robot.libraries.BuiltIn import BuiltIn, RobotNotRunningError


from RPA.Desktop.Clipboard import Clipboard
from RPA.Desktop.OperatingSystem import OperatingSystem
from RPA.Images import Images

from RPA.core.utils import delay, clean_filename

if platform.system() == "Windows":
    import ctypes
    import win32api
    import win32com.client
    import win32con
    import win32security
    import pywinauto


def write_element_info_as_json(elements, filename, path="output/json"):
    """Write list of elements into json file

    :param elements: list of elements to write
    :param filename: output file name
    :param path: output directory, defaults to "output/json"
    """
    elements = elements if isinstance(elements, list) else [elements]
    with open(Path(f"{path}/{filename}.json"), "w") as outfile:
        json.dump(elements, outfile, indent=4, sort_keys=True)


class Windows(OperatingSystem):
    """Windows methods extending OperatingSystem class.
    """

    def __init__(self, backend="uia"):
        OperatingSystem.__init__(self)
        self._apps = {}
        self._app_instance_id = 0
        self._active_app_instance = -1
        # uia or win32
        self._backend = backend
        self.app = None
        self.dlg = None
        self.windowtitle = None
        self.logger = logging.getLogger(__name__)
        self.clipboard = Clipboard()

    def __del__(self):
        try:
            # TODO: Do this as RF listener instead of __del__?
            self.clipboard.clear_clipboard()
        except RuntimeError as err:
            self.logger.debug("Failed to clear clipboard: %s", err)

    # TODO. add possibility to define alias for application
    def _add_app_instance(self, app=None, dialog=True, params=None):
        self._app_instance_id += 1
        if app is None:
            app = self.app
        else:
            self.app = app
        default_params = {
            "app": app,
            "id": self._app_instance_id,
            "dispatched": False,
        }
        if params:
            self._apps[self._app_instance_id] = {**default_params, **params}
        else:
            self._apps[self._app_instance_id] = default_params
        self._active_app_instance = self._app_instance_id
        if dialog:
            self.open_dialog(self._apps[self._app_instance_id].get("windowtitle", None))
        self.logger.info(self._apps[self._app_instance_id])
        return self._active_app_instance

    def switch_to_application(self, app_id):
        """Switch to application by id.

        :param app_id: application's id
        :raises ValueError: if application is not found by given id
        """
        if app_id and app_id in self._apps.keys():
            app = self.get_app(app_id)
            self._active_app_instance = app_id
            self.app = app["app"]
            self.open_dialog(app["windowtitle"])
            delay(0.5)
            self.restore_dialog(app["windowtitle"])
        else:
            raise ValueError(f"No open application with id '{app_id}'")

    def get_app(self, app_id=None):
        """Get application object by id

        By default returns active_application application object.

        :param app_id: id of the application to get, defaults to None
        :return: application object
        """
        if app_id is None and self._active_app_instance != -1:
            return self._apps[self._active_app_instance]
        else:
            return self._apps[app_id]

    def open_application(self, application):
        """Open application by dispatch method

        :param application: name of the application as `str`
        :return: application instance id
        """
        self.logger.info(f"open_application({application})")
        app = win32com.client.gencache.EnsureDispatch(f"{application}.Application")
        app.Visible = True
        # show eg. file overwrite warning or not
        if hasattr(self.app, "DisplayAlerts"):
            app.DisplayAlerts = False
        return self._add_app_instance(app, dialog=False, params={"dispatched": True})

    # TODO. How to manage app launched by open_file
    def open_file(self, filename):
        """Open associated application when opening file

        :param filename: path to file
        :return: True if application is opened, False if not
        """
        self.logger.info(f"open_file({filename})")
        if platform.system() == "Windows":
            # pylint: disable=no-member
            os.startfile(filename)
            return True
        elif platform.system() == "Darwin":
            subprocess.call(["open", filename])
            return True
        else:
            subprocess.call(["xdg-open", filename])
            return True

        return False

    def open_executable(self, executable, windowtitle):
        """Open Windows executable. Window title name is required
        to get handle on the application.

        :param executable: name of the executable
        :param windowtitle: name of the window
        :return: application instance id
        """
        self.logger.info(f"Opening executable: {executable} - window: {windowtitle}")
        params = {"executable": executable, "windowtitle": windowtitle}
        self.windowtitle = windowtitle
        app = pywinauto.Application(backend="uia").start(executable)
        return self._add_app_instance(app, dialog=True, params=params)

    def open_using_run_dialog(self, executable, windowtitle):
        """Open application using Windows run dialog.
        Window title name is required to get handle on the application.

        :param executable: name of the executable
        :param windowtitle: name of the window
        :return: application instance id
        """
        self.send_keys("{VK_LWIN down}r{VK_LWIN up}")
        delay(1)

        self.send_keys_to_input(executable)

        params = {"windowtitle": windowtitle, "executable": executable}
        return self._add_app_instance(params=params, dialog=True)

    def open_from_search(self, executable, windowtitle):
        """Open application using Windows search dialog.
        Window title name is required to get handle on the application.

        :param executable: name of the executable
        :param windowtitle: name of the window
        :return: application instance id
        """
        self.logger.info(f"Run from start menu: {executable}")
        self.send_keys("{LWIN}")
        delay(1)

        self.send_keys_to_input(executable)

        params = {"windowtitle": windowtitle, "executable": executable}
        return self._add_app_instance(params=params, dialog=True)

    def send_keys_to_input(
        self, keys_to_type, with_enter=True, send_delay=1.0, enter_delay=3.5
    ):
        """Send keys to windows and add ENTER if `with_enter` is True

        At the end of send_keys there is by default 1.0 second delay.
        At the end of ENTER there is by default 3.5 second delay.

        :param keys_to_type: keys to type into Windows
        :param with_enter: send ENTER if `with_enter` is True
        :param send_delay: delay after send_keys
        :param enter_delay: delay after ENTER
        """
        # Set keyboard layout for Windows platform
        if platform.system() == "Windows":
            win32api.LoadKeyboardLayout("00000409", 1)

        self.send_keys(keys_to_type)
        delay(send_delay)
        if with_enter:
            self.send_keys("{ENTER}")
            delay(enter_delay)

    def minimize_dialog(self, windowtitle):
        """Minimize window by its title

        :param windowtitle: name of the window
        """
        self.logger.info(f"minimize_dialog({windowtitle})")
        self.dlg = pywinauto.Desktop(backend="uia")[windowtitle]
        self.dlg.minimize()

    def restore_dialog(self, windowtitle):
        """Restore window by its title

        :param windowtitle: name of the window
        """
        self.logger.info(f"restore_dialog({windowtitle})")
        self.dlg = pywinauto.Desktop(backend="uia")[windowtitle]
        self.dlg.restore()

    def open_dialog(self, windowtitle=None, highlight=False):
        """Open window by its title.

        :param windowtitle: name of the window, defaults to active window if None
        :param highlight: draw outline for window if True, defaults to False
        """
        self.logger.info(f"open_dialog('{windowtitle}', '{highlight}')")
        if windowtitle:
            self.windowtitle = windowtitle
        else:
            windowtitle = self.windowtitle
        self.dlg = pywinauto.Desktop(backend="uia")[windowtitle]
        self._apps[self._active_app_instance]["dlg"] = self.dlg
        if self._apps[self._active_app_instance]["app"] is None:
            self.connect_by_handle(self.dlg.handle)
        # self.logger.info(self.dlg.print_control_identifiers())
        if highlight:
            self.dlg.draw_outline()

    def connect_by_pid(self, app_pid):
        """Connect to application by its pid

        :param app_pid: process id of the application
        """
        self.logger.info(f"Connect to application pid: {app_pid}")
        app = pywinauto.Application(backend="uia").connect(
            process=app_pid, visible_only=False
        )
        self.logger.debug(app)

    def connect_by_handle(self, handle):
        """Connect to application by its handle

        :param handle: handle of the application
        """
        self.logger.info(f"Connect to application handle: {handle}")
        self.app = pywinauto.Application(backend="uia").connect(
            handle=handle, visible_only=False
        )
        self._apps[self._active_app_instance]["app"] = self.app

    def close_all_applications(self):
        """Close all applications
        """
        self.logger.info("Closing all applications")
        application_ids = self._apps.keys()
        for aid in application_ids:
            self.quit(aid)

    def quit(self, app_id=None):
        """Quit an application by application id or
        active application if `app_id` is None.

        :param app_id: application_id, defaults to None
        """
        app = self.get_app(app_id)
        app_id_to_quit = app["id"]
        self.logger.info(f"quit application {app_id_to_quit}")
        if app["dispatched"]:
            app["app"].Quit()
        else:
            app["app"].kill()
        self._apps[app_id_to_quit]["app"] = None
        self._active_app_instance = -1

    def type_keys(self, keys):
        """Type keys into application dialog

        :param keys: list of keys to type
        """
        self.logger.info(f"type keys: {keys}")
        self.dlg.type_keys(keys)

    def send_keys(self, keys):
        """Send keys into windows

        :param keys: list of keys to send
        """
        self.logger.info(f"send keys: {keys}")
        pywinauto.keyboard.send_keys(keys)

    def mouse_click(
        self,
        locator=None,
        x=0,
        y=0,
        off_x=0,
        off_y=0,
        image=None,
        ocr=None,
        method="locator",
        ctype="click",
        screenshot=False,
    ):
        """Mouse click `locator`, `coordinates`, `image` or `ocr`.

        When using method `locator`,`image` or `ocr` mouse is clicked by default at
        center coordinates.

        Click types are:
            - `click` normal left button mouse click
            - `double`
            - `right`

        :param locator: element locator on active window
        :param x: coordinate x on desktop
        :param y: coordinate y on desktop
        :param off_x: offset x (used for locator and image clicks)
        :param off_y: offset y (used for locator and image clicks)
        :param image: image to click on desktop
        :param ocr: text to click on desktop
        :param method: one of the available methods to mouse click, default "locator"
        """
        self.logger.info(f"mouse click: {locator}")

        if method == "locator":
            self.mouse_click_locator(locator, off_x, off_y, ctype, screenshot)
        elif method == "coordinates":
            self.mouse_click_coords(x, y, ctype)
        elif method == "image":
            self.mouse_click_image(image, off_x, off_y, ctype)
        elif method == "ocr":
            self.mouse_click_ocr(ocr, off_x, off_y, ctype)

    def mouse_click_ocr(self, ocr, off_x=0, off_y=0, ctype="click"):
        """Click at ocr text on desktop

        :param ocr: [description]
        :param off_x: [description], defaults to 0
        :param off_y: [description], defaults to 0
        :param ctype: [description], defaults to "click"
        :raises NotImplementedError: [description]
        """
        raise NotImplementedError

    def mouse_click_image(self, image, off_x=0, off_y=0, ctype="click"):
        """Click at image on desktop

        :param image: [description]
        :param off_x: [description], defaults to 0
        :param off_y: [description], defaults to 0
        :param ctype: [description], defaults to "click"
        :raises NotImplementedError: [description]
        """
        raise NotImplementedError

    def mouse_click_coords(self, x, y, ctype="click"):
        """Click at coordinates on desktop

        :param x: horizontal coordinate on the windows to click
        :param y: vertical coordinate on the windows to click
        :param ctype: click type "click", "right" or "double", defaults to "click"
        """
        self.click_type(x, y, ctype)
        delay()

    def mouse_click_locator(
        self, locator, off_x=0, off_y=0, ctype="click", screenshot=False
    ):
        """Click at locator on desktop.

        By default click center of the element.

        :param locator: name of the locator
        :param off_x: horizontal offset for click, defaults to 0
        :param off_y: vertical offset for click, defaults to 0
        :param ctype: click type "click", "right" or "double", defaults to "click"
        :param screenshot: takes element screenshot if True, defaults to False
        :return: True if element was identified and click, else False
        """
        self.logger.info(f"mouse click locator: {locator}")
        # self.connect_by_handle(self.dlg.handle)
        # TODO. move dlg wait into "open_dialog" ?
        self.dlg.wait("exists enabled visible ready")
        self.open_dialog(self.windowtitle)
        search_criteria, locator = self._determine_search_criteria(locator)
        matching_elements, locators = self.find_element(locator, search_criteria)

        locators = sorted(set(locators))
        if locator in locators:
            locators.remove(locator)
        locators_string = "\n\t- ".join(locators)

        if len(matching_elements) == 0:
            self.logger.info(
                f"locator '{locator}' using search criteria '{search_criteria}'"
                f" not found in '{self.windowtitle}'.\n"
                f"Maybe one of these would be better?\n{locators_string}\n"
            )
        elif len(matching_elements) == 1:
            element = matching_elements[0]
            if screenshot:
                self.screenshot(f"locator_{locator}", element=element)
            self.logger.info(element)
            for key in element.keys():
                self.logger.debug(f"{key}={element[key]}")
            x, y = self.get_element_center(element)
            self.click_type(x + off_x, y + off_y, ctype)
            # TODO. remove delay() - for demo only ?
            delay()
            return True
        else:
            # TODO. return more valuable information about what should
            # be matching element ?
            self.logger.info(
                f"locator '{locator}' matched multiple elements"
                f" in '{self.windowtitle}'. "
                f"Maybe one of these would be better?\n{locators_string}\n"
            )
        return False

    def menu_select(self, menuitem):
        """Select item from menu

        :param menuitem: name of the menu item
        """
        self.logger.info(f"menu select: {menuitem}")
        app = self.get_app()
        app["dlg"].menu_select(menuitem)
        # self.logger.warning(f"Window '{app['windowtitle']}'
        # does not have menu_select")

    def find_element(self, locator, search_criteria):
        """Find element from window by locator and criteria.

        :param locator: name of locator
        :param search_criteria: criteria by which element is matched
        :return: list of matching elements and locators that where found on the window
        """
        self.logger.info(
            f"find element, locator: {locator} - criteria: {search_criteria}"
        )
        locators = []
        matching_elements = []
        _, elements = self.get_window_elements()
        for element in elements:
            if self.is_element_matching(element, locator, search_criteria):
                matching_elements.append(element)
            if search_criteria == "any" and "name" in element:
                locators.append(element["name"])
            elif search_criteria and search_criteria in element:
                locators.append(element[search_criteria])
        return matching_elements, locators

    def _determine_search_criteria(self, locator):
        """Check search criteria from locator.

        Possible search criterias:
            - name
            - class (class_name)
            - type (contro_type)
            - id (automation_id)
            - any if none was defined

        :param locator: name of the locator
        :return: criteria and locator
        """
        search_criteria = "any"
        if locator.startswith("name:"):
            search_criteria = "name"
            locator = "".join(locator.split("name:")[1:])
        elif locator.startswith("class:"):
            search_criteria = "class_name"
            locator = "".join(locator.split("class:")[1:])
        elif locator.startswith("type:"):
            search_criteria = "control_type"
            locator = "".join(locator.split("type:")[1:])
        elif locator.startswith("id:"):
            search_criteria = "automation_id"
            locator = "".join(locator.split("id:")[1:])
        return search_criteria, locator

    # TODO. supporting multiple search criterias at same time to identify ONE element
    def is_element_matching(self, itemdict, locator, criteria):
        """Is element matching. Check if locator is found in `any` field
        or `criteria` field in the window items.

        :param itemDict: dictionary of element items
        :param locator: name of the locator
        :param criteria: criteria on which to match element
        :return: True if element is matching locator and criteria, False if not
        """
        if criteria != "any" and criteria in itemdict and itemdict[criteria] == locator:
            return True
        elif criteria == "any":
            name_search = self.is_element_matching(itemdict, locator, "name")
            class_search = self.is_element_matching(itemdict, locator, "class_name")
            type_search = self.is_element_matching(itemdict, locator, "control_type")
            id_search = self.is_element_matching(itemdict, locator, "automation_id")
            if name_search or class_search or type_search or id_search:
                return True
        return False

    def get_dialog_rectangle(self, ctrl=None):
        """Get element rectangle coordinates

        If `ctrl` is None then get coordinates from `dialog`
        :param ctrl: name of the window control object, defaults to None
        :return: coordinates: left, top, right, bottom
        """
        if ctrl:
            rect = ctrl.element_info.rectangle
        else:
            rect = self.dlg.element_info.rectangle
        return rect.left, rect.top, rect.right, rect.bottom

    def get_element_center(self, itemdict):
        """Get element center coordinates

        :param itemDict: dictionary of element items
        :return: coordinates, x and y
        """
        left, top, right, bottom = self.get_element_coordinates(itemdict["rectangle"])
        self.logger.info(f"locator rectangle ({left}, {top}, {right}, {bottom})")

        x = int((right - left) / 2) + left
        y = int((bottom - top) / 2) + top
        return x, y

    def click_type(self, x=None, y=None, click_type="click"):
        """Mouse click on coordinates x and y.

        Default click type is `click` meaning `left`

        :param x: horizontal coordinate for click, defaults to None
        :param y: vertical coordinate for click, defaults to None
        :param click_type: "click", "right" or "double", defaults to "click"
        :raises ValueError: if coordinates are not valid
        """
        self.logger.info(f"click type '{click_type}' at ({x}, {y})")
        if (x is None and y is None) or (x < 0 or y < 0):
            raise ValueError("Can't click on given coordinates: ({x}, {y})")
        if click_type == "click":
            pywinauto.mouse.click(coords=(x, y))
        elif click_type == "double":
            pywinauto.mouse.double_click(coords=(x, y))
        elif click_type == "right":
            pywinauto.mouse.right_click(coords=(x, y))

    def get_window_elements(self, screenshot=False, element_json=False, outline=False):
        """Get element information about all window dialog control and their descendants.

        :param screenshot: save element screenshot if True, defaults to False
        :param element_json: save element json if True, defaults to False
        :param outline: highlight elements if True, defaults to False
        :return: all controls and all elements
        """
        self.logger.info("get window elements")
        # Create a list of this control and all its descendants
        all_ctrls = [self.dlg]
        if hasattr(self.dlg, "descendants"):
            all_ctrls += self.dlg.descendants()
        # self.logger.debug(type(self.dlg))
        # self.logger.debug(dir(self.dlg))
        all_elements = []
        for _, ctrl in enumerate(all_ctrls):
            if hasattr(ctrl, "element_info"):
                cleaned_filename = clean_filename(
                    f"locator_{self.windowtitle}_ctrl_{ctrl.element_info.name}"
                )
                if screenshot and len(ctrl.element_info.name) > 0:
                    self.screenshot(cleaned_filename, ctrl=ctrl)
                if outline:
                    ctrl.draw_outline(colour="red", thickness=4)
                    delay(0.2)
                    ctrl.draw_outline(colour=0x000000, thickness=4)
                element = self.get_element_attributes(element=ctrl)
                if element_json:
                    write_element_info_as_json(element, cleaned_filename)
                all_elements.append(element)
        if element_json:
            write_element_info_as_json(
                all_elements, clean_filename(f"locator_{self.windowtitle}_all_elements")
            )
        # self.logger.info(self.dlg.print_control_identifiers())
        return all_ctrls, all_elements

    def get_element_coordinates(self, rectangle):
        """Get element coordinates from pywinauto object.

        :param rectangle: item containing rectangle information
        :return: coordinates: left, top, right, bottom
        """
        left, top, right, bottom = map(
            int, re.match(r"\(L(\d+).*T(\d+).*R(\d+).*B(\d+)\)", rectangle).groups()
        )
        return left, top, right, bottom

    def screenshot(self, filename, element=None, ctrl=None, desktop=False):
        """Save screenshot into filename.

        :param filename: name of the file
        :param element: take element screenshot if True, defaults to None
        :param ctrl: take control screenshot if True, defaults to None
        :param desktop: take desktop screenshot if True, defaults to False
        """
        if desktop:
            region = None
        elif element:
            region = self.get_element_coordinates(element["rectangle"])
        elif ctrl:
            region = self.get_dialog_rectangle(ctrl)
        else:
            region = self.get_dialog_rectangle()

        try:
            output_dir = BuiltIn().get_variable_value("${OUTPUT_DIR}")
        except (ModuleNotFoundError, RobotNotRunningError):
            output_dir = Path.cwd()

        filename = Path(output_dir, "images", clean_filename(filename))
        os.makedirs(filename.parent)
        Images().take_screenshot(filename=filename, region=region)

        self.logger.info("Saved screenshot as '%s'", filename)

    def get_element_attributes(self, element):
        """Return filtered element dictionary for an element.

        :param element: should contain `element_info` attribute
        :return: dictionary containing element attributes
        """
        # self.logger.debug(f"get_element_attributes: {element}")
        if element is None or not hasattr(element, "element_info"):
            self.logger.warning(
                f"{element} is none or does not have element_info attribute"
            )
            return None

        attributes = [
            "automation_id",
            # "children",
            "class_name",
            "control_id",
            "control_type",
            # "descendants",
            # "dump_window",
            # "element"
            "enabled",
            # "filter_with_depth",
            # "framework_id",
            # "from_point",
            "handle",
            # "has_depth",
            # "iter_children",
            # "iter_descendants",
            "name",
            # "parent",
            "process_id",
            "rectangle",
            "rich_text",
            "runtime_id",
            # "set_cache_strategy",
            # "top_from_point",
            "visible",
        ]

        element_dict = {}
        # self.element_info = backend.registry.backends[_backend].element_info_class()
        element_info = element.element_info
        # self.logger.debug(element_info)
        for attr in attributes:
            if hasattr(element_info, attr):
                attr_value = getattr(element_info, attr)
                try:
                    element_dict[attr] = (
                        attr_value() if callable(attr_value) else str(attr_value)
                    )
                except TypeError:
                    pass
            else:
                self.logger.warning(f"did not have attr {attr}")
        return element_dict

    def window_exists(self):
        raise NotImplementedError

    def put_system_to_sleep(self):
        """Put Windows into sleep mode
        """
        access = win32security.TOKEN_ADJUST_PRIVILEGES | win32security.TOKEN_QUERY
        htoken = win32security.OpenProcessToken(win32api.GetCurrentProcess(), access)
        if htoken:
            priv_id = win32security.LookupPrivilegeValue(
                None, win32security.SE_SHUTDOWN_NAME
            )
            win32security.AdjustTokenPrivileges(
                htoken, 0, [(priv_id, win32security.SE_PRIVILEGE_ENABLED)]
            )
            ctypes.windll.powrprof.SetSuspendState(False, True, True)
            win32api.CloseHandle(htoken)

    def lock_screen(self):
        """Put windows into lock mode
        """
        ctypes.windll.User32.LockWorkStation()

    def log_in(self, username, password, domain="."):
        """Log into Windows `domain` with `username` and `password`.

        :param username: name of the user
        :param password: password of the user
        :param domain: windows domain for the user, defaults to "."
        """
        return win32security.LogonUser(
            username,
            domain,
            password,
            win32con.LOGON32_LOGON_INTERACTIVE,
            win32con.LOGON32_PROVIDER_DEFAULT,
        )