/** Превью элемента медиа-галереи товара (FEATURES.md 4.4 ревизия) — фото
 * или видео в одном списке, различаем по префиксу mime_type. Видео —
 * без controls/autoplay, просто первый кадр как статичное превью
 * (кликабельность/воспроизведение здесь не нужны, это витрина в кабинете).
 */
interface MediaThumbnailProps {
  src: string;
  mimeType: string;
  alt: string;
  className?: string;
}

export function MediaThumbnail({ src, mimeType, alt, className = "" }: MediaThumbnailProps) {
  if (mimeType.startsWith("video/")) {
    return (
      <video
        src={src}
        muted
        playsInline
        preload="metadata"
        aria-label={alt}
        className={className}
      />
    );
  }
  return <img src={src} alt={alt} className={className} />;
}
