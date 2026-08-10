import { flushPromises, mount } from '@vue/test-utils'
import { defineComponent, h } from 'vue'
import { afterEach, describe, expect, it } from 'vitest'
import TimedMediaPreviewSurface from './TimedMediaPreviewSurface.vue'

const playerCalls = []
const wrappers = []

function playerStub(name, className, emits) {
  return defineComponent({
    name,
    props: ['src', 'title', 'cacheKey', 'poster', 'thumbnailVttUrl'],
    emits,
    setup(props, { emit, expose }) {
      expose({
        seek: (seconds) => playerCalls.push([name, 'seek', seconds]),
        togglePlayback: () => playerCalls.push([name, 'toggle']),
      })
      return () => h('button', {
        class: className,
        onClick: () => {
          emit('time-update', 12.5)
          if (emits.includes('playback-change')) emit('playback-change', true)
        },
      }, props.src)
    },
  })
}

const ArtAudioPlayerStub = playerStub(
  'ArtAudioPlayer',
  'audio-player-stub',
  ['time-update', 'playback-change'],
)
const ArtVideoPlayerStub = playerStub('ArtVideoPlayer', 'video-player-stub', ['time-update'])

function mountSurface(props = {}) {
  const wrapper = mount(TimedMediaPreviewSurface, {
    props: {
      tab: { id: 'content:one', title: '标签标题' },
      content: { id: 'one', title: '媒体标题', content_type: 'video' },
      ...props,
    },
    global: {
      stubs: {
        ArtAudioPlayer: ArtAudioPlayerStub,
        ArtVideoPlayer: ArtVideoPlayerStub,
        SvgMaskIcon: true,
      },
    },
  })
  wrappers.push(wrapper)
  return wrapper
}

afterEach(() => {
  wrappers.splice(0).forEach((wrapper) => wrapper.unmount())
  playerCalls.length = 0
})

describe('TimedMediaPreviewSurface', () => {
  it('bridges audio player events, seek and playback controls', async () => {
    const wrapper = mountSurface({
      audio: true,
      timedMedia: true,
      mediaUrl: 'http://127.0.0.1:8000/api/media/audio.m4a',
      content: { id: 'one', title: '访谈', content_type: 'audio' },
    })
    await flushPromises()

    const player = wrapper.getComponent(ArtAudioPlayerStub)
    expect(player.props('src')).toContain('audio.m4a')
    expect(player.props('title')).toBe('访谈')
    expect(player.props('cacheKey')).toBe('content:one')
    expect(wrapper.vm.hasPlayer()).toBe(true)

    await player.trigger('click')
    expect(wrapper.emitted('time-update')).toEqual([[12.5]])
    expect(wrapper.emitted('playback-change')).toEqual([[true]])

    wrapper.vm.seek(45)
    wrapper.vm.togglePlayback()
    expect(playerCalls).toEqual([
      ['ArtAudioPlayer', 'seek', 45],
      ['ArtAudioPlayer', 'toggle'],
    ])
  })

  it('keeps video player source, poster, thumbnails and time updates', async () => {
    const wrapper = mountSurface({
      timedMedia: true,
      mediaUrl: 'http://127.0.0.1:8000/api/media/video.mp4',
      content: {
        id: 'one', title: '课程', content_type: 'video',
        cover_url: '/api/media/cover.jpg', thumbnail_vtt_url: '/api/media/thumbs.vtt',
      },
    })
    await flushPromises()

    const player = wrapper.getComponent(ArtVideoPlayerStub)
    expect(player.props('poster')).toBe('/api/media/cover.jpg')
    expect(player.props('thumbnailVttUrl')).toBe('/api/media/thumbs.vtt')
    await player.trigger('click')
    expect(wrapper.emitted('time-update')).toEqual([[12.5]])
  })

  it('preserves cover loading and expired-cache status', () => {
    const wrapper = mountSurface({
      timedMedia: true,
      videoCacheExpired: true,
      videoCacheExpiredLabel: '2026-08-10 09:30',
      content: {
        id: 'one', content_type: 'video', status: 'processing', cover_url: '/api/media/cover.jpg',
      },
    })

    expect(wrapper.get('.media-cover-image').attributes('src')).toBe('/api/media/cover.jpg')
    expect(wrapper.vm.hasPlayer()).toBe(false)
    expect(wrapper.get('.media-cache-expired').text()).toContain('2026-08-10 09:30')
    expect(wrapper.get('.media-preview-loader').attributes('aria-label')).toBe('正在加载视频预览')
  })

  it('distinguishes empty processing media from the durable retry placeholder', async () => {
    const wrapper = mountSurface({
      timedMedia: true,
      content: { id: 'one', content_type: 'video', status: 'processing' },
    })
    expect(wrapper.get('.media-preview-loader.is-empty').attributes('aria-label')).toBe('正在加载媒体预览')

    await wrapper.setProps({
      videoCacheExpired: true,
      content: { id: 'one', content_type: 'video', status: 'ready' },
    })
    expect(wrapper.get('.media-placeholder').text()).toContain('本地视频预览已过期')
  })
})
