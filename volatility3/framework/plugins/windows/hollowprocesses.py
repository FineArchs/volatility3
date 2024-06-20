# This file is Copyright 2019 Volatility Foundation and licensed under the Volatility Software License 1.0
# which is available at https://www.volatilityfoundation.org/license/vsl-v1.0
#
import logging
from typing import NamedTuple

from volatility3.framework import interfaces, exceptions, constants
from volatility3.framework import renderers
from volatility3.framework.configuration import requirements
from volatility3.framework.objects import utility
from volatility3.plugins.windows import pslist, vadinfo

vollog = logging.getLogger(__name__)

VadInfo = NamedTuple(
    "VadInfo",
    [
        ("protection", str),
        ("path", str),
   ],
)

DLLInfo = NamedTuple(
    "DLLInfo",
    [
        ("path", str),
   ],
)

class HollowProcesses(interfaces.plugins.PluginInterface):
    """Lists hollowed processes"""

    _required_framework_version = (2, 4, 0)

    @classmethod
    def get_requirements(cls):
        # Since we're calling the plugin, make sure we have the plugin's requirements
        return [
            requirements.ModuleRequirement(
                name="kernel",
                description="Windows kernel",
                architectures=["Intel32", "Intel64"],
            ),
            requirements.ListRequirement(
                name="pid",
                element_type=int,
                description="Process IDs to include (all other processes are excluded)",
                optional=True,
            ),
            requirements.VersionRequirement(
                name="pslist", component=pslist.PsList, version=(2, 0, 0)
            ),
            requirements.VersionRequirement(
                name="vadinfo", component=vadinfo.VadInfo, version=(2, 0, 0)
            ),
        ]

    def _get_vads_map(self, proc):
        vads = {}

        kernel = self.context.modules[self.config["kernel"]]

        for vad in proc.get_vad_root().traverse():
            protection_string = vad.get_protection(
                vadinfo.VadInfo.protect_values(
                    self.context, kernel.layer_name, kernel.symbol_table_name
                ),
                vadinfo.winnt_protections,
            )

            fn = vad.get_file_name()
            if not fn or not isinstance(fn, str):
                fn = "<Non-File Backed Region>"

            vads[vad.get_start()] = VadInfo(protection_string, fn)

        return vads

    def _get_dlls_map(self, proc):
        dlls = {}

        for entry in proc.load_order_modules():
            try:
                base = entry.DllBase
            except exceptions.InvalidAddressException:
                continue

            try:
                FullDllName = entry.FullDllName.get_string()
            except exceptions.InvalidAddressException:
                FullDllName = renderers.UnreadableValue()

            dlls[base] = DLLInfo(FullDllName)

        return dlls

    def _get_image_base(self, proc):
        kernel = self.context.modules[self.config["kernel"]]

        try:
            proc_layer_name = proc.add_process_layer()
            peb = self.context.object(
                kernel.symbol_table_name + constants.BANG + "_PEB",
                layer_name=proc_layer_name,
                offset=proc.Peb,
            )
            return peb.ImageBaseAddress
        except exceptions.InvalidAddressException:
            return None

    def _check_load_address(self, proc, _, __):
        image_base = self._get_image_base(proc)
        if image_base is not None and image_base != proc.SectionBaseAddress:
            yield "The ImageBaseAddress reported from the PEB ({:#x}) does not match the process SectionBaseAddress ({:#x})".format(image_base, proc.SectionBaseAddress)

    def _check_exe_protection(self, proc, vads, __):
        base = proc.SectionBaseAddress

        if base not in vads:
            yield "There is no VAD starting at the base address of the process executable ({:#x})".format(base)
        elif vads[base].protection != "PAGE_EXECUTE_WRITECOPY":
            yield "Unexpected protection ({}) for VAD hosting the process executable ({:#x}) with path {}".format(vads[base].protection, base, vads[base].path)

    def _check_dlls_protection(self, _, vads, dlls):
        for dll_base in dlls:
            # could be malicious but triggers too many FPs from smear
            if dll_base not in vads:
                continue

            if vads[dll_base].protection != "PAGE_EXECUTE_WRITECOPY":
                yield "Unexpected protection ({}) for DLL in the PEB's load order list ({:#x}) with path {}".format(vads[dll_base].protection, dll_base, dlls[dll_base].path)

    def _generator(self, procs):
        checks = [self._check_load_address, self._check_exe_protection, self._check_dlls_protection]

        for proc in procs:
            proc_name = utility.array_to_string(proc.ImageFileName)
            pid = proc.UniqueProcessId

            # smear and/or terminated process
            dlls = self._get_dlls_map(proc)
            if len(dlls) < 3:
                continue

            vads = self._get_vads_map(proc)
            if len(vads) < 5:
                continue

            for check in checks:
                for note in check(proc, vads, dlls):
                    yield 0, (
                        pid,
                        proc_name,
                        note,
                    )

    def run(self):
        filter_func = pslist.PsList.create_pid_filter(self.config.get("pid", None))
        kernel = self.context.modules[self.config["kernel"]]

        return renderers.TreeGrid(
            [
                ("PID", int),
                ("Process", str),
                ("Notes", str),
            ],
            self._generator(
                pslist.PsList.list_processes(
                    context=self.context,
                    layer_name=kernel.layer_name,
                    symbol_table=kernel.symbol_table_name,
                    filter_func=filter_func,
                )
            ),
        )
