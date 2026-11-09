# Exports the data sets the Python tutorial reads, from the R packages the R
# tutorial uses. Run from this folder: Rscript make_data.R
library(dplyr)

janeaustenr::austen_books() |>
  group_by(book) |>
  mutate(linenumber = row_number()) |>
  ungroup() |>
  mutate(book = as.character(book)) |>
  select(book, linenumber, text) |>
  write.csv("austen_books.csv", row.names = FALSE)

tidytext::get_sentiments("bing") |>
  write.csv("bing.csv", row.names = FALSE)
