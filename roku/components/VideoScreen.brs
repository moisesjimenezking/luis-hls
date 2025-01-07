sub init()
    video = m.top.findNode("video")
    video.content = createObject("roSGNode", "ContentNode")
    video.content.url = "https://www.cuaimateam.online/hls/cuaima-tv.m3u8" ' Reemplaza con tu URL de HLS
    video.content.streamFormat = "hls"
    video.control = "play"
end sub
