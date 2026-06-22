/* === Share Trade as Image === */

async function captureTradeImage(element) {
  // Temporarily hide remove buttons, hints, and share button
  const hideEls = element.querySelectorAll('.trade-remove-btn, .remove-btn, .scout-trade-hint, .drop-hint, .share-btn');
  hideEls.forEach(el => el.style.display = 'none');

  try {
    const canvas = await html2canvas(element, {
      backgroundColor: '#0d1117',
      useCORS: true,
      scale: 2,
      logging: false,
    });

    // Draw watermark on the canvas directly
    const ctx = canvas.getContext('2d');
    ctx.font = '600 ' + (11 * 2) + 'px -apple-system, BlinkMacSystemFont, sans-serif';
    ctx.fillStyle = '#484f58';
    ctx.textAlign = 'center';
    ctx.fillText('dynastz.com', canvas.width / 2, canvas.height - 12);

    return new Promise(resolve => canvas.toBlob(resolve, 'image/png'));
  } finally {
    hideEls.forEach(el => el.style.display = '');
  }
}

async function shareTradeImage(blob) {
  const file = new File([blob], 'dynast-z-trade.png', { type: 'image/png' });

  // Try Web Share API (mobile)
  if (navigator.canShare && navigator.canShare({ files: [file] })) {
    try {
      await navigator.share({ files: [file] });
      return;
    } catch (e) {
      if (e.name === 'AbortError') return;
    }
  }

  // Try clipboard
  try {
    await navigator.clipboard.write([
      new ClipboardItem({ 'image/png': blob })
    ]);
    showShareToast('Trade snapshot was copied!');
    return;
  } catch (e) {
    // fall through to download
  }

  // Fallback: download
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = 'dynast-z-trade.png';
  a.click();
  URL.revokeObjectURL(url);
  showShareToast('Trade snapshot was saved!');
}

function showShareToast(message) {
  const existing = document.querySelector('.share-toast');
  if (existing) existing.remove();
  const toast = document.createElement('div');
  toast.className = 'share-toast';
  toast.textContent = message;
  document.body.appendChild(toast);
  setTimeout(() => toast.classList.add('visible'), 10);
  setTimeout(() => {
    toast.classList.remove('visible');
    setTimeout(() => toast.remove(), 300);
  }, 2000);
}

function createShareButton(onClick) {
  const btn = document.createElement('button');
  btn.className = 'share-btn';
  btn.title = 'Share trade image';
  btn.textContent = 'Share';
  btn.addEventListener('click', async () => {
    btn.disabled = true;
    try {
      await onClick();
    } finally {
      btn.disabled = false;
    }
  });
  return btn;
}
