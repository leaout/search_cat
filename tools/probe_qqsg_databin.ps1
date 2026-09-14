param([string]$GameDirectory = 'D:\WeGameApps\QQ三国')

$dll = Join-Path $GameDirectory 'DataBin.dll'
$source = @"
using System;
using System.Runtime.InteropServices;
public static class QQSGDataBinProbe {
    [DllImport(@"$dll", EntryPoint="CreateDataBinMgr", CallingConvention=CallingConvention.Cdecl)]
    public static extern IntPtr CreateDataBinMgr();
    [DllImport(@"$dll", EntryPoint="DestroyDataBinMgr", CallingConvention=CallingConvention.Cdecl)]
    public static extern void DestroyDataBinMgr(IntPtr value);
    [DllImport("kernel32.dll", CharSet=CharSet.Ansi)]
    public static extern IntPtr GetModuleHandle(string name);
}
"@
Add-Type -TypeDefinition $source
[Environment]::CurrentDirectory = $GameDirectory
$manager = [QQSGDataBinProbe]::CreateDataBinMgr()
try {
    [pscustomobject]@{
        Loaded = ($manager -ne [IntPtr]::Zero)
        Pointer = ('0x{0:X8}' -f $manager.ToInt32())
        ProcessBits = 32
        ModuleBase = ('0x{0:X8}' -f [QQSGDataBinProbe]::GetModuleHandle('DataBin.dll').ToInt32())
        Vtable = @(0..15 | ForEach-Object {
            $table = [Runtime.InteropServices.Marshal]::ReadIntPtr($manager)
            $address = [Runtime.InteropServices.Marshal]::ReadIntPtr($table, $_ * 4)
            '0x{0:X8}' -f ($address.ToInt32() - [QQSGDataBinProbe]::GetModuleHandle('DataBin.dll').ToInt32())
        })
        ManagerSlots = @(0..15 | ForEach-Object {
            $address = [Runtime.InteropServices.Marshal]::ReadIntPtr($manager, 4 + $_ * 4)
            '0x{0:X8}' -f $address.ToInt32()
        })
    } | ConvertTo-Json
} finally {
    if ($manager -ne [IntPtr]::Zero) {
        [QQSGDataBinProbe]::DestroyDataBinMgr($manager)
    }
}
