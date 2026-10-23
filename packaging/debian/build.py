#!/usr/bin/env python3
"""Build an offline, dependency-managed Debian 13 package without root."""
import argparse,os,re,shutil,subprocess,tempfile
from pathlib import Path

repo=Path(__file__).resolve().parents[2]
p=argparse.ArgumentParser();p.add_argument('--output',type=Path,default=repo/'dist');args=p.parse_args()
version=re.search(r'__version__\s*=\s*"([^"]+)"',(repo/'otam/__init__.py').read_text()).group(1)
args.output.mkdir(parents=True,exist_ok=True)
with tempfile.TemporaryDirectory(prefix='otam-deb-') as tmp:
    root=Path(tmp)/'package';control=root/'DEBIAN';control.mkdir(parents=True)
    site=root/'usr/lib/python3/dist-packages';site.mkdir(parents=True)
    shutil.copytree(repo/'otam',site/'otam',ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
    bin=root/'usr/bin';bin.mkdir(parents=True)
    (bin/'otam').write_text('#!/usr/bin/python3\nfrom otam.cli import main\nraise SystemExit(main())\n');(bin/'otam').chmod(0o755)
    doc=root/'usr/share/doc/opentape-archive-manager';doc.mkdir(parents=True)
    for source,dest in [(repo/'LICENSE',doc/'copyright'),(repo/'README.md',doc/'README.md')]:shutil.copy2(source,dest)
    shutil.copytree(repo/'docs',doc/'docs',ignore=shutil.ignore_patterns('hardware','*.sqlite','__pycache__'))
    (doc/'docs/hardware').mkdir()
    shutil.copy2(repo/'docs/hardware/README.md',doc/'docs/hardware/README.md')
    shutil.copytree(repo/'packaging/udev',doc/'examples/udev')
    shutil.copytree(repo/'packaging/systemd',doc/'examples/systemd')
    units=root/'usr/lib/systemd/system';units.mkdir(parents=True)
    for name in ('otam-web.service','otam-worker.service'):
        s=(repo/'packaging/systemd'/name).read_text().replace('/opt/otam/venv/bin/otam','/usr/bin/otam')
        s=s.replace('[Unit]\n','[Unit]\nConditionPathExists=/etc/otam/node.json\n',1)
        (units/name).write_text(s)
    (control/'control').write_text(f'''Package: opentape-archive-manager
Version: {version}
Section: admin
Priority: optional
Architecture: all
Maintainer: OTAM contributors <otam@users.noreply.github.com>
Depends: python3 (>= 3.11), python3-fastapi (>= 0.115), python3-uvicorn, python3-httpx, adduser, init-system-helpers
Suggests: mt-st, mbuffer, sg3-utils, lsscsi
Homepage: https://github.com/MichaelH1981/opentape-archive-manager
Description: Local tape archive manager with verified PAX archives
 Web UI, durable worker, SHA-256 verification, persistent local staging and
 optional standalone catalog. Physical writes require explicit configuration.
 No default password; first administrator enrollment uses a private local token.
''')
    for name in ('preinst','postinst','prerm','postrm'):
        shutil.copy2(repo/'packaging/debian'/name,control/name);(control/name).chmod(0o755)
    # Do not inherit a private source umask into executable/package permissions.
    for d,dirs,files in os.walk(root):
        Path(d).chmod(0o755)
        for name in files:
            path=Path(d)/name
            if path not in [control/n for n in ('preinst','postinst','prerm','postrm')] and path!=bin/'otam':path.chmod(0o644)
    out=args.output/f'opentape-archive-manager_{version}_all.deb'
    subprocess.run(['dpkg-deb','--root-owner-group','--build',str(root),str(out)],check=True)
    print(out)
