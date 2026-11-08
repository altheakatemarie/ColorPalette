from collections import defaultdict
from io import BytesIO
import warnings

from flask import Flask, jsonify, render_template, request
from PIL import Image, ImageOps, UnidentifiedImageError
from werkzeug.exceptions import RequestEntityTooLarge

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 8 * 1024 * 1024
Image.MAX_IMAGE_PIXELS = 20_000_000


@app.get("/")
def home():
    return render_template("index.html")


@app.errorhandler(RequestEntityTooLarge)
def too_large(error):
    return jsonify(error="Upload an image smaller than 8 MB."), 413


@app.post("/api/extract")
def extract():
    upload = request.files.get("image")

    if upload is None or not upload.filename:
        return jsonify(error="Please select an image."), 400

    mode = request.form.get("count", "5").strip().lower()

    if mode != "auto":
        try:
            count = int(mode)
        except ValueError:
            return jsonify(
                error="Choose Auto Extraction or 1–10 colors."
            ), 400

        if not 1 <= count <= 10:
            return jsonify(
                error="Choose Auto Extraction or 1–10 colors."
            ), 400

    try:
        raw = upload.read()

        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)

            with Image.open(BytesIO(raw)) as check:
                if check.format not in ("JPEG", "PNG"):
                    return jsonify(
                        error="Only JPG and PNG images are supported."
                    ), 400

                if check.width * check.height > 20_000_000:
                    return jsonify(
                        error="Use an image at or below 20 megapixels."
                    ), 400

                check.verify()

            with Image.open(BytesIO(raw)) as source:
                image = ImageOps.exif_transpose(source).convert("RGBA")
                image.thumbnail((300, 300))

                pixels = []

                for red, green, blue, alpha in image.getdata():
                    if alpha == 0:
                        continue

                    pixels.append(tuple(
                        round(
                            (value * alpha + 255 * (255 - alpha)) / 255
                        )
                        for value in (red, green, blue)
                    ))

        if not pixels:
            return jsonify(
                error="This image is completely transparent."
            ), 400

        grouped = defaultdict(int)

        if mode == "auto":
            # Group similar shades using 32-level RGB intervals.
            # Return every occupied group, without a top-10 cutoff.
            bins = {}

            for rgb in pixels:
                key = tuple(value // 32 for value in rgb)
                totals = bins.setdefault(key, [0, 0, 0, 0])

                for index, value in enumerate(rgb):
                    totals[index] += value

                totals[3] += 1

            for totals in bins.values():
                frequency = totals[3]
                rgb = tuple(
                    round(value / frequency)
                    for value in totals[:3]
                )
                grouped[rgb] += frequency

        else:
            sample = Image.new("RGB", (len(pixels), 1))
            sample.putdata(pixels)

            quantized = sample.quantize(
                colors=count,
                method=Image.Quantize.MEDIANCUT,
                dither=Image.Dither.NONE,
            )

            palette = quantized.getpalette()

            for frequency, index in quantized.getcolors():
                offset = index * 3
                rgb = tuple(palette[offset:offset + 3])
                grouped[rgb] += frequency

        colors = []

        for rgb, frequency in sorted(
            grouped.items(),
            key=lambda item: (-item[1], item[0])
        ):
            colors.append({
                "hex": "#{:02X}{:02X}{:02X}".format(*rgb),
                "rgb": list(rgb),
                "percentage": round(
                    frequency / len(pixels) * 100, 2
                ),
            })

        return jsonify(
            colors=colors,
            mode=mode,
            count=len(colors),
        )

    except (
        Image.DecompressionBombWarning,
        Image.DecompressionBombError,
    ):
        return jsonify(
            error="Image is too large. Use an image at or below 20 megapixels."
        ), 400

    except (UnidentifiedImageError, OSError, ValueError, SyntaxError):
        return jsonify(
            error="Invalid or damaged image. Try another JPG or PNG."
        ), 400


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False)