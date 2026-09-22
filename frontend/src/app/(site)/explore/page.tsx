import { redirect } from "next/navigation";

/** Keep existing Explore links pointed at the single faculty homepage. */
export default function ExplorePage() {
  redirect("/");
}
