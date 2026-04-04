from __future__ import annotations

from typing import TYPE_CHECKING

from flask import Blueprint, jsonify, request

from streamonitor.utils import normalize_streamer_username

from .serializers import streamer_detail_dict, streamer_recordings_list, streamer_status_dict

if TYPE_CHECKING:
    from streamonitor.managers.httpmanager.httpmanager import HTTPManager

MAX_BULK_STATUS_ITEMS = 200


def create_api_v1_blueprint(manager: HTTPManager, login_required):
    bp = Blueprint("api_v1", __name__, url_prefix="/api/v1")

    def _get_streamer_or_none(username: str, site: str):
        return manager.getStreamer(username, site)

    @bp.route("/streams", methods=["POST"])
    @login_required
    def post_add_stream():
        body = request.get_json(silent=True) or {}
        username = (body.get("username") or "").strip()
        site = (body.get("site") or "").strip()
        if not username or not site:
            return jsonify({"error": "username and site are required"}), 400
        username = normalize_streamer_username(username, site)
        if not username:
            return jsonify({"error": "username and site are required"}), 400
        existing = _get_streamer_or_none(username, site)
        res = manager.do_add(existing, username, site)
        if res == "Streamer already exists":
            return jsonify({"error": res}), 409
        if res == "Missing value(s)":
            return jsonify({"error": res}), 400
        if isinstance(res, str) and res.startswith("Failed to add"):
            return jsonify({"error": res}), 502
        streamer = _get_streamer_or_none(username, site)
        if streamer is None:
            return jsonify({"error": "added but streamer not found"}), 500
        return jsonify({"message": res, "streamer": streamer_detail_dict(streamer)}), 201

    @bp.route("/streams/<username>/<site>", methods=["GET"])
    @login_required
    def get_stream_detail(username, site):
        streamer = _get_streamer_or_none(username, site)
        if streamer is None:
            return jsonify({"error": "streamer not found"}), 404
        return jsonify({"streamer": streamer_detail_dict(streamer)}), 200

    @bp.route("/streams/<username>/<site>", methods=["DELETE"])
    @login_required
    def delete_stream(username, site):
        streamer = _get_streamer_or_none(username, site)
        res = manager.do_remove(streamer, username, site)
        if res in ("Streamer not found", "Failed to remove streamer"):
            return jsonify({"error": res}), 404
        return "", 204

    @bp.route("/streams/<username>/<site>/recordings", methods=["GET"])
    @login_required
    def get_stream_recordings(username, site):
        streamer = _get_streamer_or_none(username, site)
        if streamer is None:
            return jsonify({"error": "streamer not found"}), 404
        sort_by_size = (request.args.get("sort") or "").lower() == "size"
        items = streamer_recordings_list(streamer, sort_by_size=sort_by_size)
        return jsonify({"recordings": items, "total_bytes": streamer.video_files_total_size}), 200

    @bp.route("/streams/<username>/<site>/status", methods=["GET"])
    @login_required
    def get_stream_status(username, site):
        streamer = _get_streamer_or_none(username, site)
        if streamer is None:
            return jsonify({"error": "streamer not found"}), 404
        refresh = (request.args.get("refresh") or "").lower() in ("1", "true", "yes")
        return jsonify(streamer_status_dict(streamer, refresh=refresh)), 200

    @bp.route("/streams/status", methods=["POST"])
    @login_required
    def post_streams_status_bulk():
        body = request.get_json(silent=True) or {}
        items = body.get("streams")
        if not isinstance(items, list):
            return jsonify({"error": "body must include 'streams' array"}), 400
        if len(items) > MAX_BULK_STATUS_ITEMS:
            return jsonify(
                {"error": f"at most {MAX_BULK_STATUS_ITEMS} streams per request"}
            ), 400
        refresh = (request.args.get("refresh") or "").lower() in ("1", "true", "yes")
        results = []
        for raw in items:
            if not isinstance(raw, dict):
                results.append(
                    {"ok": False, "error": "each stream must be an object", "username": None, "site": None}
                )
                continue
            u = (raw.get("username") or "").strip()
            s = (raw.get("site") or "").strip()
            if not u or not s:
                results.append(
                    {
                        "ok": False,
                        "error": "username and site required",
                        "username": u or None,
                        "site": s or None,
                    }
                )
                continue
            streamer = _get_streamer_or_none(u, s)
            if streamer is None:
                results.append(
                    {
                        "ok": False,
                        "error": "streamer not found",
                        "username": u,
                        "site": s,
                    }
                )
                continue
            results.append(streamer_status_dict(streamer, refresh=refresh))
        return jsonify({"results": results}), 200

    return bp
