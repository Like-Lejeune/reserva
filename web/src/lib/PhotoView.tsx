import { useEffect, useState } from "react";
import { photoBlob } from "./store";
import type { Photo } from "./types";

/** Affiche une photo locale, ou la télécharge une fois si elle vient d'un autre appareil. */
export function PhotoView({ photo, className }: { photo?: Photo; className?: string }) {
  const [url, setUrl] = useState("");
  useEffect(() => {
    if (!photo) return setUrl("");
    let created = "";
    let alive = true;
    void photoBlob(photo).then((blob) => {
      if (!blob || !alive) return;
      created = URL.createObjectURL(blob);
      setUrl(created);
    });
    return () => {
      alive = false;
      if (created) URL.revokeObjectURL(created);
    };
  }, [photo?.id, !!photo?.blob]); // eslint-disable-line react-hooks/exhaustive-deps
  return url ? <img src={url} alt="" className={className} /> : <div className={`${className ?? ""} ph`}>📷</div>;
}
