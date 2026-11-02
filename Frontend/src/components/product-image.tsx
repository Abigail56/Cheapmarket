import { LeafIcon } from "./icons";

// Product photos come from the API's /media folder or Cloudinary, so a plain <img> is used
// (next/image would need every image host configured ahead of time)
export function ProductImage({
  src,
  alt,
  className = "",
  eager = false,
}: {
  src: string | null;
  alt: string;
  className?: string;
  eager?: boolean;
}) {
  if (!src) {
    return (
      <div className={`grid place-items-center bg-linear-to-br from-brand-50 to-brand-100 text-brand-300 ${className}`}>
        <LeafIcon width={40} height={40} />
      </div>
    );
  }
  return (
    // eslint-disable-next-line @next/next/no-img-element
    <img src={src} alt={alt} loading={eager ? "eager" : "lazy"} className={`object-cover ${className}`} />
  );
}
