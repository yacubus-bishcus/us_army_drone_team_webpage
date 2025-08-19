# test_softwarefiles.py
from dotenv import load_dotenv
load_dotenv()  # make sure .env is loaded
from skynet import create_app
from skynet.extensions import db
from skynet.models import SoftwareFile
from datetime import datetime
import os
app = create_app()
with app.app_context():
    os.makedirs(os.path.join(app.instance_path, "uploads", "software", "cad"), exist_ok=True)
    os.makedirs(os.path.join(app.instance_path, "uploads", "software", "uas"), exist_ok=True)
    # (Place some dummy files in those folders so downloads work.)

    demo = [
        SoftwareFile(category="cad", name="Frame Mount v1", description="Universal camera mount.", version="1.0",
                     license="CC-BY", filetype="STL", tags="mount,camera",
                     filename="frame_mount_v1.stl", filesize=1536000),
        SoftwareFile(category="cad", name="Airframe STEP", description="Full airframe parametric model.",
                     version="0.9", license="CC0", filetype="STEP", tags="airframe,frame",
                     filename="airframe.step", filesize=5632000),
        SoftwareFile(category="uas", name="PX4 Firmware Patch", description="Patch for GPS failsafe.",
                     version="2.1", license="BSD-3", filetype="Firmware", tags="PX4,failsafe,GPS",
                     filename="px4_patch.bin", filesize=1048576),
        SoftwareFile(category="uas", name="MAVLink Tool", description="CLI tool for MAVLink routes.",
                     version="0.3", license="MIT", filetype="Python", tags="MAVLink,tools",
                     filename="mavlink_tool.py", filesize=40960),
    ]
    db.session.add_all(demo)
    db.session.commit()
    print("Seeded demo rows. Add the files under instance/uploads/software/<cad|uas>/")
