/**
 * Cloudflare Pages Function — API 同域代理
 * 将 /api/* 请求转发到 Cloudflare Tunnel 后端，消除浏览器跨域开销
 * 架构: 浏览器 → Pages(同域) → Function → Tunnel → VPS:8000
 */

const BACKEND = 'https://quant-api.stephenhe.com/api/v1'

export const onRequestGet = proxy
export const onRequestPost = proxy
export const onRequestPut = proxy
export const onRequestDelete = proxy
export const onRequestPatch = proxy

async function proxy(context: { request: Request }): Promise<Response> {
  const { request } = context
  const url = new URL(request.url)
  const target = `${BACKEND}${url.pathname.replace('/api/v1', '')}${url.search}`

  // 转发请求头，移除 Host（fetch 会自动设置正确的 Host）
  const headers = new Headers(request.headers)
  headers.delete('host')
  headers.delete('content-length')
  headers.delete('cf-connecting-ip')
  headers.delete('cf-ray')
  headers.delete('cf-visitor')

  try {
    const response = await fetch(target, {
      method: request.method,
      headers,
      body: request.method !== 'GET' && request.method !== 'HEAD' ? await request.arrayBuffer() : undefined,
    })

    // 构建响应，透传后端头
    const responseHeaders = new Headers(response.headers)
    responseHeaders.delete('cf-connecting-ip')
    responseHeaders.delete('cf-ray')

    return new Response(response.body, {
      status: response.status,
      statusText: response.statusText,
      headers: responseHeaders,
    })
  } catch {
    return new Response(
      JSON.stringify({ code: 502, msg: 'Backend unreachable', data: null }),
      { status: 502, headers: { 'Content-Type': 'application/json' } }
    )
  }
}
