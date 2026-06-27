export function getRelativeTimeText(isoString) {
  if (!isoString) return "--";
  
  const targetTime = new Date(isoString).getTime();
  const now = Date.now();
  const diff = targetTime - now;

  // 如果时间已经过去
  if (diff <= 0) return "已发布";

  const diffMins = Math.floor(diff / (1000 * 60));
  const diffHours = Math.floor(diffMins / 60);
  const diffDays = Math.floor(diffHours / 24);

  if (diffDays > 0) {
    return `还有 ${diffDays} 天`;
  } else if (diffHours > 0) {
    const remainMins = diffMins % 60;
    return `还有 ${diffHours} 小时 ${remainMins > 0 ? remainMins + ' 分' : ''}`;
  } else {
    // 小于1小时，高亮显示分钟
    return `还有 ${diffMins} 分钟`;
  }
}
