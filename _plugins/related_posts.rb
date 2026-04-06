# Override the related_posts method from jekyll-tagging-related_posts
# to prioritize posts with the most shared tags first.
module Jekyll
  module Tagging
    module RelatedPosts
      def related_posts
        return [] unless docs.count > 1

        highest_freq = tag_freq.values.max
        scores = {}

        docs.each do |doc|
          next if doc == self

          shared_tags = self.data["tags"] & doc.data["tags"]
          next if shared_tags.empty?

          # Primary: number of shared tags (more overlap = better match)
          shared_count = shared_tags.size

          # Secondary: rarity-weighted sum (same as original plugin)
          rarity_score = shared_tags.sum { |t| 1 + highest_freq - tag_freq[t] }

          scores[doc] = [shared_count, rarity_score]
        end

        scores.sort { |a, b|
          cmp = b[1][0] <=> a[1][0]
          cmp = b[1][1] <=> a[1][1] if cmp == 0
          cmp = b[0].date <=> a[0].date if cmp == 0
          cmp
        }.map(&:first)
      end
    end
  end
end
