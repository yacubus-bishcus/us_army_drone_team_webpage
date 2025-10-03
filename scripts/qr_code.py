import qrcode

# URL for the Army Drone Team website
url = "https://usarmydroneteam.onrender.com"

# Generate QR code
qr = qrcode.QRCode(
    version=1,  # controls size of the QR Code (1 is smallest, 40 is largest)
    error_correction=qrcode.constants.ERROR_CORRECT_H,  # high error correction
    box_size=10,  # size of each box in pixels
    border=4,  # border thickness
)

qr.add_data(url)
qr.make(fit=True)

# Create an image (black QR on white background)
img = qr.make_image(fill_color="black", back_color="white")

# Save the QR code as a PNG
img.save("army_drone_team_qr.png")

print("QR code generated and saved as army_drone_team_qr.png")
