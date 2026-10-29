"""Now-playing card using the same scoped models and controls as other widgets."""
from ..components import IconButton, Column, Image, Row, Text, component, use_model
from ..artwork import ArtworkModel
from ..now_playing import NowPlayingModel, PREFIX, can_control


@component
def NowPlaying(config):
    model = use_model(NowPlayingModel, key="now-playing")
    player, error, busy = model.view()
    props = player["properties"] if player else {}
    metadata = props.get("Metadata", {})
    artwork = use_model(ArtworkModel, key="artwork").view(metadata.get("mpris:artUrl", ""))
    title = metadata.get("xesam:title") or ("Unknown track" if player else "Nothing playing")
    artists = metadata.get("xesam:artist", [])
    artist = artists if isinstance(artists, str) else ", ".join(artists)
    album = metadata.get("xesam:album", "")
    status = props.get("PlaybackStatus", "")
    source = player["name"][len(PREFIX):].split(".")[0] if player else "Open a media player to get started"
    return Column(
        Text("NOW PLAYING", class_name="widget-label", key="label"),
        Image(artwork, class_name="media-artwork", key="artwork"),
        Text(title, wrap=True, max_width_chars=28, class_name="media-title", key="title"),
        Text(artist, visible=bool(artist), wrap=True, max_width_chars=28, key="artist"),
        Text(album, visible=bool(album), wrap=True, max_width_chars=28,
             class_name="media-detail", key="album"),
        Row(*(IconButton(icon, label=label, class_name="media-control", on_click=lambda method=method: model.control(method),
                     sensitive=not busy and can_control(player, method), expand=True, key=method)
              for method, icon, label in (("Previous", "backward-step", "Previous"),
                                    ("PlayPause", "pause" if status == "Playing" else "play",
                                     "Pause" if status == "Playing" else "Play"),
                                    ("Next", "forward-step", "Next"))), spacing=8),
        Text(error or (f"{source} · {status}" if status else source), wrap=True,
             max_width_chars=28, class_name="media-detail", key="status"),
        spacing=8, class_name="media-card",
    )
