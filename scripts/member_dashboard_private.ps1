param([Parameter(Mandatory=$true)][string]$Path,
      [ValidateSet('check','initialize')][string]$Mode='check')
$ErrorActionPreference='Stop'
$item=Get-Item -LiteralPath $Path -Force
if($item.Attributes -band [IO.FileAttributes]::ReparsePoint){throw 'Reparse points are not private state'}
$sid=[Security.Principal.WindowsIdentity]::GetCurrent().User
$allowed=@($sid.Value,'S-1-5-18','S-1-5-32-544')
if($Mode -eq 'initialize'){
  if(-not $item.PSIsContainer){throw 'Private directory required'}
  if(@(Get-ChildItem -LiteralPath $Path -Force).Count -ne 0){throw 'Only an empty new directory may be initialized'}
  $acl=New-Object Security.AccessControl.DirectorySecurity
  $acl.SetOwner($sid)
  $acl.SetAccessRuleProtection($true,$false)
  foreach($entry in $allowed){
    $identity=New-Object Security.Principal.SecurityIdentifier($entry)
    $rule=New-Object Security.AccessControl.FileSystemAccessRule($identity,'FullControl','ContainerInherit,ObjectInherit','None','Allow')
    $acl.AddAccessRule($rule)
  }
  [IO.Directory]::SetAccessControl($item.FullName,$acl)
}
if($item.PSIsContainer){$acl=[IO.Directory]::GetAccessControl($item.FullName)}else{$acl=[IO.File]::GetAccessControl($item.FullName)}
if($allowed -notcontains $acl.GetOwner([Security.Principal.SecurityIdentifier]).Value){throw 'Private owner required'}
$allowed+='S-1-3-4' # OWNER RIGHTS applies only to the verified owner above.
foreach($rule in $acl.GetAccessRules($true,$true,[Security.Principal.SecurityIdentifier])){
  if($rule.AccessControlType -eq 'Allow' -and $allowed -notcontains $rule.IdentityReference.Value){throw 'Private access required'}
}
