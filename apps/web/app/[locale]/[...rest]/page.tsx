import { notFound } from "next/navigation";

// Any URL under a locale that matches no real route falls through here and
// triggers the localized, branded not-found.tsx (next-intl pattern: an
// unmatched path otherwise hits Next's default global 404).
export default function CatchAllNotFound() {
  notFound();
}
