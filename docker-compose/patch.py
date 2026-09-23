import glob
import pathlib
import sys

site_packages = glob.glob('/app/.venv/lib/python3*/site-packages')
if not site_packages:
    sys.exit('ERROR: /app/.venv site-packages not found')


def read(rel: str) -> tuple[pathlib.Path, str]:
    path = pathlib.Path(site_packages[0], 'litellm/proxy', rel)
    return path, path.read_text()


license_path, license_content = read('auth/litellm_license.py')
def_idx = license_content.find('def is_premium(')
try_idx = license_content.find('try:', def_idx)
if def_idx == -1 or try_idx == -1:
    print('ERROR: is_premium body not found in litellm_license.py')
elif 'return True' in license_content[def_idx:try_idx]:
    print('litellm_license.py: already patched, skipping')
else:
    line_start = license_content.rfind('\n', 0, try_idx) + 1
    license_content = license_content[:line_start] + '        return True\n' + license_content[line_start:]
    license_path.write_text(license_content)
    print('litellm_license.py: license check disabled')

sso_path, sso_content = read('management_endpoints/ui_sso.py')
if 'billable_users > 50:' in sso_content:
    print('ui_sso.py: already patched, skipping')
elif 'billable_users > 5:' not in sso_content:
    print('ERROR: free user limit check not found in ui_sso.py')
else:
    sso_content = sso_content.replace('billable_users > 5:', 'billable_users > 50:', 1)
    sso_content = sso_content.replace('up to 5 billable users', 'up to 50 billable users', 1)
    sso_content = sso_content.replace('more than 5 users', 'more than 50 users', 1)
    sso_path.write_text(sso_content)
    print('ui_sso.py: SSO free user limit raised to 50')
