// app.js - 应急决策教学系统 小程序入口
App({
  // 全局配置
  globalData: {
    // 后端服务地址（部署后替换为你的HTTPS域名）
    // 本地开发时可用 http://127.0.0.1:5000，正式发布必须是HTTPS
    apiBase: 'https://your-domain.com',

    // web-view内嵌的页面地址
    webUrl: 'https://your-domain.com/login',

    // 用户登录Token（登录后保存）
    token: '',

    // 用户信息
    userInfo: null
  },

  onLaunch() {
    // 小程序启动时执行
    console.log('应急决策教学系统 启动')

    // 从本地存储读取Token
    const token = wx.getStorageSync('token')
    if (token) {
      this.globalData.token = token
      // 根据Token决定进入哪个页面
      this.checkLogin()
    }
  },

  // 检查登录状态
  checkLogin() {
    const token = this.globalData.token
    if (!token) {
      this.globalData.webUrl = this.globalData.apiBase + '/login'
      return
    }

    // 验证Token是否有效
    wx.request({
      url: this.globalData.apiBase + '/api/session',
      method: 'GET',
      header: {
        'Authorization': 'Bearer ' + token
      },
      success: (res) => {
        if (res.data && res.data.logged_in) {
          // 已登录，直接进入系统主页
          this.globalData.webUrl = this.globalData.apiBase + '/dashboard?token=' + token
          this.globalData.userInfo = res.data.user
        } else {
          // Token失效，跳转登录
          this.globalData.webUrl = this.globalData.apiBase + '/login'
          wx.removeStorageSync('token')
        }
      },
      fail: () => {
        // 网络错误，默认进入登录页
        this.globalData.webUrl = this.globalData.apiBase + '/login'
      }
    })
  }
})
