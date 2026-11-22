"""枚举 UVC Camera 的 KS 节点。只打开滤镜，不拉流。"""

import comtypes
from comtypes import COMMETHOD, GUID, HRESULT, IUnknown, CoCreateInstance
from comtypes.automation import VARIANT
from ctypes import POINTER, c_ulong, c_void_p, c_wchar_p
from ctypes.wintypes import DWORD, ULONG


class IEnumMoniker(IUnknown):
    _iid_ = GUID("{00000102-0000-0000-C000-000000000046}")


class IMoniker(IUnknown):
    _iid_ = GUID("{0000000F-0000-0000-C000-000000000046}")


IEnumMoniker._methods_ = [
    COMMETHOD(
        [],
        HRESULT,
        "Next",
        (["in"], ULONG, "celt"),
        (["out"], POINTER(POINTER(IMoniker)), "rgelt"),
        (["out"], POINTER(ULONG), "fetched"),
    ),
    COMMETHOD([], HRESULT, "Skip", (["in"], ULONG, "celt")),
    COMMETHOD([], HRESULT, "Reset"),
    COMMETHOD([], HRESULT, "Clone", (["out"], POINTER(POINTER(IEnumMoniker)), "ppenum")),
]

IMoniker._methods_ = [
    COMMETHOD([], HRESULT, "GetClassID", (["out"], POINTER(GUID), "clsid")),
    COMMETHOD([], HRESULT, "IsDirty"),
    COMMETHOD([], HRESULT, "Load", (["in"], c_void_p, "stream")),
    COMMETHOD([], HRESULT, "Save", (["in"], c_void_p, "stream"), (["in"], c_ulong, "clear")),
    COMMETHOD([], HRESULT, "GetSizeMax", (["out"], POINTER(c_ulong), "size")),
    COMMETHOD(
        [],
        HRESULT,
        "BindToObject",
        (["in"], c_void_p, "bindctx"),
        (["in"], c_void_p, "left"),
        (["in"], POINTER(GUID), "iid"),
        (["out"], POINTER(POINTER(IUnknown)), "obj"),
    ),
    COMMETHOD(
        [],
        HRESULT,
        "BindToStorage",
        (["in"], c_void_p, "bindctx"),
        (["in"], c_void_p, "left"),
        (["in"], POINTER(GUID), "iid"),
        (["out"], POINTER(POINTER(IUnknown)), "obj"),
    ),
]


class IPropertyBag(IUnknown):
    _iid_ = GUID("{55272A00-42CB-11CE-8135-00AA004BB851}")
    _methods_ = [
        COMMETHOD(
            [],
            HRESULT,
            "Read",
            (["in"], c_wchar_p, "name"),
            (["in", "out"], POINTER(VARIANT), "value"),
            (["in"], c_void_p, "errorlog"),
        ),
        COMMETHOD(
            [],
            HRESULT,
            "Write",
            (["in"], c_wchar_p, "name"),
            (["in"], POINTER(VARIANT), "value"),
        ),
    ]


class ICreateDevEnum(IUnknown):
    _iid_ = GUID("{29840822-5B84-11D0-BD3B-00A0C911CE86}")
    _methods_ = [
        COMMETHOD(
            [],
            HRESULT,
            "CreateClassEnumerator",
            (["in"], POINTER(GUID), "category"),
            (["out"], POINTER(POINTER(IEnumMoniker)), "enum"),
            (["in"], DWORD, "flags"),
        )
    ]


class IKsTopologyInfo(IUnknown):
    _iid_ = GUID("{720D4AC0-7533-11D0-A5D6-28DB04C10000}")
    _methods_ = [
        COMMETHOD([], HRESULT, "get_NumNodes", (["out"], POINTER(DWORD), "num")),
        COMMETHOD(
            [],
            HRESULT,
            "get_NodeType",
            (["in"], DWORD, "node"),
            (["out"], POINTER(GUID), "kind"),
        ),
        COMMETHOD(
            [],
            HRESULT,
            "get_NodeName",
            (["in"], DWORD, "node"),
            (["in"], c_wchar_p, "name"),
            (["in"], DWORD, "buf"),
            (["out"], POINTER(DWORD), "needed"),
        ),
        COMMETHOD(
            [],
            HRESULT,
            "get_NumCategories",
            (["in"], DWORD, "node"),
            (["out"], POINTER(DWORD), "num"),
        ),
        COMMETHOD(
            [],
            HRESULT,
            "get_Category",
            (["in"], DWORD, "node"),
            (["in"], DWORD, "index"),
            (["out"], POINTER(GUID), "category"),
        ),
        COMMETHOD(
            [],
            HRESULT,
            "CreateNodeInstance",
            (["in"], DWORD, "node"),
            (["in"], POINTER(GUID), "iid"),
            (["out"], POINTER(POINTER(IUnknown)), "obj"),
        ),
    ]


CLSID_SystemDeviceEnum = GUID("{62BE5D10-60EB-11d0-BD3B-00A0C911CE86}")
CLSID_VideoInputDeviceCategory = GUID("{860BB310-5D01-11d0-BD3B-00A0C911CE86}")


def main() -> None:
    dev_enum = CoCreateInstance(CLSID_SystemDeviceEnum, interface=ICreateDevEnum)
    monikers = dev_enum.CreateClassEnumerator(CLSID_VideoInputDeviceCategory, 0)
    while True:
        moniker, fetched = monikers.Next(1)
        if not fetched:
            break
        bag = moniker.BindToStorage(None, None, IPropertyBag._iid_).QueryInterface(IPropertyBag)
        value = VARIANT()
        bag.Read("FriendlyName", value, None)
        name = value.value
        print("DEVICE", name, "vt", value.vt)
        unk = moniker.BindToObject(None, None, IUnknown._iid_)
        topo = unk.QueryInterface(IKsTopologyInfo)
        count = int(topo.get_NumNodes())
        print("nodes", count)
        for node in range(count):
            kind = topo.get_NodeType(node)
            print(" ", node, kind)


if __name__ == "__main__":
    main()
