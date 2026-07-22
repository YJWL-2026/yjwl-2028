// pages/index/index.js - 首页逻辑
const app = getApp()

Page({
  data: {
    webUrl: '',      // web-view加载的URL
    loading: true,    // 加载状态
    loadError: false  // 加载失败
  },

  onLoad(options) {
    // 从全局配置获取URL
    this.setData({
      webUrl: app.globalData.webUrl,
      loading: true
    })
  },

  // web-view加载成功
  onLoad(e) {
    console.log('WebView加载成功', e)
    this.setData({ loading: false, loadError: false })
  },

  // web-view加载失败
  onError(e) {
    console.error('WebView加载失败', e)
    this.setData({ loading: false, loadError: true })
  },

  // 接收web-view传来的消息
  onMessage(e) {
    console.log('收到WebView消息:', e.detail)
    const data = e.detail.data[0]

    // 处理网页发来的消息
    if (data && data.action) {
      switch (data.action) {
        case 'logout':
          // 网页退出登录，清除Token
          wx.removeStorageSync('token')
          app.globalData.token = ''
          app.globalData.webUrl = app.globalData.apiBase + '/login'
          this.setData({ webUrl: app.globalData.webUrl })
          break

        case 'login_success':
          // 网页登录成功，保存Token
          if (data.token) {
            wx.setStorageSync('token', data.token)
            app.globalData.token = data.token
          }
          break

        case 'navigate':
          // 网页请求跳转小程序页面
          if (data.page) {
            wx.navigateTo({ url: data.page })
          }
          break
      }
    }
  },

  // 重新加载
  retry() {
    this.setData({ loading: true, loadError: false })
    this.setData({ webUrl: this.data.webUrl + (this.data.webUrl.includes('?') ? '&' : '?') + 't=' + Date.now() })
  },

  // 分享
  onShareAppMessage() {
    return {
      title: '应急决策教学系统',
      path: '/pages/index/index'
    }
  }
})
