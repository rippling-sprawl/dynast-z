/* === Share Trade as Image === */

async function captureTradeImage(element) {
  // Temporarily hide remove buttons and hints
  const removeButtons = element.querySelectorAll('.trade-remove-btn, .remove-btn');
  const hints = element.querySelectorAll('.scout-trade-hint, .drop-hint');
  removeButtons.forEach(btn => btn.style.display = 'none');
  hints.forEach(h => h.style.display = 'none');

  // Add watermark
  const watermark = document.createElement('div');
  watermark.className = 'share-watermark';
  watermark.textContent = 'dynastz.com';
  element.appendChild(watermark);

  try {
    const canvas = await html2canvas(element, {
      backgroundColor: '#0d1117',
      useCORS: true,
      scale: 2,
      logging: false,
    });
    return new Promise(resolve => canvas.toBlob(resolve, 'image/png'));
  } finally {
    removeButtons.forEach(btn => btn.style.display = '');
    hints.forEach(h => h.style.display = '');
    watermark.remove();
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
      if (e.name === 'AbortError') return; // user cancelled
    }
  }

  // Try clipboard
  try {
    await navigator.clipboard.write([
      new ClipboardItem({ 'image/png': blob })
    ]);
    showShareToast('Copied to clipboard');
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
  showShareToast('Image saved');
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
  btn.innerHTML = '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M4 12v8a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-8"/><polyline points="16 6 12 2 8 6"/><line x1="12" y1="2" x2="12" y2="15"/></svg>';
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
