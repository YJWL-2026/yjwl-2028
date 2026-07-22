// pages/login/login.js - 原生登录页
const app = getApp()

Page({
  data: {
    activeTab: 'teacher',
    username: '',
    password: '',
    loggingIn: false
  },

  // 切换角色Tab
  switchTab(e) {
    const tab = e.currentTarget.dataset.tab
    this.setData({ activeTab: tab, username: '', password: '' })
  },

  // 输入账号
  onUsernameInput(e) {
    this.setData({ username: e.detail.value })
  },

  // 输入密码
  onPasswordInput(e) {
    this.setData({ password: e.detail.value })
  },

  // 快速填充演示账号
  fillDemo(e) {
    this.setData({
      username: e.currentTarget.dataset.user,
      password: e.currentTarget.dataset.pass
    })
  },

  // 执行登录
  doLogin() {
    const { username, password } = this.data

    if (!username) {
      wx.showToast({ title: '请输入账号', icon: 'none' })
      return
    }
    if (!password) {
      wx.showToast({ title: '请输入密码', icon: 'none' })
      return
    }

    this.setData({ loggingIn: true })

    // 调用后端登录API
    wx.request({
      url: app.globalData.apiBase + '/api/auth/token',
      method: 'POST',
      header: { 'Content-Type': 'application/json' },
      data: { username, password },
      success: (res) => {
        if (res.statusCode === 200 && res.data.token) {
          // 登录成功，保存Token
          wx.setStorageSync('token', res.data.token)
          app.globalData.token = res.data.token
          app.globalData.userInfo = res.data.user

          // 跳转到首页（WebView内嵌系统）
          wx.redirectTo({ url: '/pages/index/index' })

          wx.showToast({ title: '登录成功', icon: 'success' })
        } else {
          wx.showToast({
            title: res.data.error || '登录失败',
            icon: 'none'
          })
        }
      },
      fail: (err) => {
        console.error('登录请求失败:', err)
        wx.showToast({
          title: '网络错误，请检查服务器地址',
          icon: 'none',
          duration: 3000
        })
      },
      complete: () => {
        this.setData({ loggingIn: false })
      }
    })
  }
})
