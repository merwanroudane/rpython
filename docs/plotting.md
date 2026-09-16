# Plotting

```python
import rpython as rp
r = rp.R()
res = r.eval("plot(mtcars$wt, mtcars$mpg)")
res.plot.save("scatter.png")
g = r("ggplot2::ggplot(mtcars, ggplot2::aes(wt, mpg)) + ggplot2::geom_point()")
g.save("scatter.svg")                       # png / svg / pdf (ggsave); html for htmlwidgets
print(r.last.plot is not None)
```

Base graphics, ggplot2, lattice go to PNG automatically; in Jupyter they display inline. Python matplotlib figures created inside a Python worker driven by R are captured the same way.
